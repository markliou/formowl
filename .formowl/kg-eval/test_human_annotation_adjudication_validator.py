#!/usr/bin/env python3
"""Tests for real human annotation/adjudication evidence validation."""

from __future__ import annotations

import json
import shutil
import unittest

import human_annotation_adjudication_validator as validator
import llm_subagent_adjudication as llm_panel
import public_reproducible_evidence as public_evidence


BASE = validator.REAL_ARTIFACT_ROOT_PATH / "validator_fixture"
LLM_PANEL_RUBRIC_SHA256 = "a1234567890bcdef" * 4


def write_artifact(relative_name: str, payload: object) -> tuple[str, str]:
    path = BASE / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return (
        f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/{relative_name}",
        validator.sha256_file(path) or "",
    )


def write_non_real_artifact(relative_name: str, payload: object) -> tuple[str, str]:
    path = validator.INPUTS / "test_human_annotation_rejected" / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"inputs/test_human_annotation_rejected/{relative_name}", validator.sha256_file(
        path
    ) or ""


def remove_path(path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)


def build_report_for_test(packet: dict) -> dict:
    return validator.build_report(packet, allow_test_artifacts=True)


def rewrite_packet_artifact(packet: dict, artifact_field: str, mutate) -> dict:
    path = validator.safe_relative_artifact_path(
        packet[artifact_field],
        allow_test_artifacts=True,
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    packet[f"{artifact_field}_sha256"] = validator.sha256_file(path) or ""
    return payload


def rewrite_first_pass_artifact(packet: dict, index: int, mutate) -> dict:
    ref = packet["first_pass_submission_artifacts"][index]
    path = validator.safe_relative_artifact_path(
        ref["artifact"],
        allow_test_artifacts=True,
    )
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ref["artifact_sha256"] = validator.sha256_file(path) or ""
    return payload


def _rebind_downstream_after_first_pass_change(
    packet: dict,
    alpha_payload: dict,
    beta_payload: dict,
) -> None:
    first_pass_rows = alpha_payload["rows"] + beta_payload["rows"]

    def mutate_adjudication(payload: dict) -> None:
        payload["first_pass_rows_sha256"] = validator.sha256_json(first_pass_rows)

    rewrite_packet_artifact(packet, "adjudication_artifact", mutate_adjudication)

    def mutate_confusion(payload: dict) -> None:
        payload["adjudication_artifact_sha256"] = packet["adjudication_artifact_sha256"]

    rewrite_packet_artifact(packet, "confusion_matrix_artifact", mutate_confusion)

    def mutate_custody(payload: dict) -> None:
        payload["first_pass_submission_artifact_sha256s"] = sorted(
            ref["artifact_sha256"] for ref in packet["first_pass_submission_artifacts"]
        )
        payload["adjudication_artifact_sha256"] = packet["adjudication_artifact_sha256"]
        payload["confusion_matrix_artifact_sha256"] = packet["confusion_matrix_artifact_sha256"]

    rewrite_packet_artifact(packet, "custody_receipt_artifact", mutate_custody)


def valid_packet() -> dict:
    manifest_items = [
        validator.with_row_hash(
            {
                "item_id": "ann_item_invoice_001",
                "task_id": "evidence_supported_claim",
                "source_ref": "formowl://observation/obs_mail_invoice_001",
                "source_observation_id": "obs_mail_invoice_001",
                "consensus_label": "supported",
            }
        ),
        validator.with_row_hash(
            {
                "item_id": "ann_item_decision_001",
                "task_id": "business_decision_candidate",
                "source_ref": "formowl://observation/obs_meeting_segment_004",
                "source_observation_id": "obs_meeting_segment_004",
                "consensus_label": "needs_review",
            }
        ),
    ]
    manifest = {
        "artifact_type": "human_annotation_manifest_v1",
        "annotation_task_id": "kg_eval_annotation_v1",
        "item_count": len(manifest_items),
        "items": manifest_items,
    }
    manifest_artifact, manifest_sha = write_artifact("manifest.json", manifest)

    work_order_rows = [
        validator.with_row_hash(
            {
                "work_order_id": "wo_alpha_invoice",
                "reviewer_id": "human_reviewer_alpha",
                "role": "first_pass",
                "item_id": "ann_item_invoice_001",
                "manifest_row_sha256": manifest_items[0]["row_sha256"],
            }
        ),
        validator.with_row_hash(
            {
                "work_order_id": "wo_beta_invoice",
                "reviewer_id": "human_reviewer_beta",
                "role": "first_pass",
                "item_id": "ann_item_invoice_001",
                "manifest_row_sha256": manifest_items[0]["row_sha256"],
            }
        ),
        validator.with_row_hash(
            {
                "work_order_id": "wo_alpha_decision",
                "reviewer_id": "human_reviewer_alpha",
                "role": "first_pass",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_items[1]["row_sha256"],
            }
        ),
        validator.with_row_hash(
            {
                "work_order_id": "wo_beta_decision",
                "reviewer_id": "human_reviewer_beta",
                "role": "first_pass",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_items[1]["row_sha256"],
            }
        ),
        validator.with_row_hash(
            {
                "work_order_id": "wo_gamma_decision",
                "reviewer_id": "human_adjudicator_gamma",
                "role": "adjudicator",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_items[1]["row_sha256"],
            }
        ),
    ]
    work_orders = {
        "artifact_type": "human_annotation_work_orders_v1",
        "work_orders": work_order_rows,
    }
    work_orders_artifact, work_orders_sha = write_artifact("work_orders.json", work_orders)

    alpha_rows = [
        validator.with_row_hash(
            {
                "submission_id": "alpha_invoice",
                "reviewer_id": "human_reviewer_alpha",
                "work_order_id": "wo_alpha_invoice",
                "item_id": "ann_item_invoice_001",
                "manifest_row_sha256": manifest_items[0]["row_sha256"],
                "label": "supported",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
        validator.with_row_hash(
            {
                "submission_id": "alpha_decision",
                "reviewer_id": "human_reviewer_alpha",
                "work_order_id": "wo_alpha_decision",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_items[1]["row_sha256"],
                "label": "supported",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
    ]
    beta_rows = [
        validator.with_row_hash(
            {
                "submission_id": "beta_invoice",
                "reviewer_id": "human_reviewer_beta",
                "work_order_id": "wo_beta_invoice",
                "item_id": "ann_item_invoice_001",
                "manifest_row_sha256": manifest_items[0]["row_sha256"],
                "label": "supported",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
        validator.with_row_hash(
            {
                "submission_id": "beta_decision",
                "reviewer_id": "human_reviewer_beta",
                "work_order_id": "wo_beta_decision",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_items[1]["row_sha256"],
                "label": "needs_review",
                "generated_by_llm": False,
                "template_source": None,
            }
        ),
    ]

    alpha_submission = {
        "artifact_type": "human_first_pass_submission_v1",
        "reviewer_id": "human_reviewer_alpha",
        "reviewer_type": "human",
        "independent_first_pass": True,
        "sealed": True,
        "generated_by_llm": False,
        "template_source": None,
        "rows": alpha_rows,
        "submission_set_sha256": validator.sha256_json(
            sorted(row["row_sha256"] for row in alpha_rows)
        ),
    }
    beta_submission = {
        "artifact_type": "human_first_pass_submission_v1",
        "reviewer_id": "human_reviewer_beta",
        "reviewer_type": "human",
        "independent_first_pass": True,
        "sealed": True,
        "generated_by_llm": False,
        "template_source": None,
        "rows": beta_rows,
        "submission_set_sha256": validator.sha256_json(
            sorted(row["row_sha256"] for row in beta_rows)
        ),
    }
    alpha_artifact, alpha_sha = write_artifact("first_pass_alpha.json", alpha_submission)
    beta_artifact, beta_sha = write_artifact("first_pass_beta.json", beta_submission)

    first_pass_rows = alpha_rows + beta_rows
    disagreements = validator._expected_disagreements(
        {
            "ann_item_invoice_001": [alpha_rows[0], beta_rows[0]],
            "ann_item_decision_001": [alpha_rows[1], beta_rows[1]],
        }
    )
    disagreement_sha = validator.sha256_json(disagreements)
    adjudication_rows = [
        validator.with_row_hash(
            {
                "adjudication_id": "adj_decision",
                "adjudicator_id": "human_adjudicator_gamma",
                "work_order_id": "wo_gamma_decision",
                "item_id": "ann_item_decision_001",
                "manifest_row_sha256": manifest_items[1]["row_sha256"],
                "final_label": "needs_review",
                "sealed_disagreement_set_sha256": disagreement_sha,
                "generated_by_llm": False,
                "template_source": None,
            }
        )
    ]
    adjudication = {
        "artifact_type": "human_final_adjudication_v1",
        "opened_after_first_pass_seal": True,
        "adjudicator_id": "human_adjudicator_gamma",
        "adjudicator_type": "human",
        "generated_by_llm": False,
        "template_source": None,
        "manifest_artifact_sha256": manifest_sha,
        "first_pass_rows_sha256": validator.sha256_json(first_pass_rows),
        "sealed_disagreement_set": disagreements,
        "sealed_disagreement_set_sha256": disagreement_sha,
        "rows": adjudication_rows,
    }
    adjudication_artifact, adjudication_sha = write_artifact("adjudication.json", adjudication)

    confusion_matrix = {
        "artifact_type": "annotation_confusion_matrix_v1",
        "adjudication_artifact_sha256": adjudication_sha,
        "item_count": 2,
        "final_label_counts": {"supported": 1, "needs_review": 1},
        "generated_by_llm": False,
    }
    confusion_artifact, confusion_sha = write_artifact("confusion_matrix.json", confusion_matrix)

    custody = {
        "artifact_type": "annotation_custody_receipt_v1",
        "complete": True,
        "human_packet_complete": True,
        "manifest_artifact_sha256": manifest_sha,
        "work_orders_artifact_sha256": work_orders_sha,
        "first_pass_submission_artifact_sha256s": sorted([alpha_sha, beta_sha]),
        "adjudication_artifact_sha256": adjudication_sha,
        "confusion_matrix_artifact_sha256": confusion_sha,
        "response_packet_sha256": "fedcba0987654321" * 4,
        "custody_receipt_sha256": "1234567890abcdef" * 4,
    }
    custody_artifact, custody_sha = write_artifact("custody.json", custody)

    return {
        "artifact_id": "human_annotation_results_v1",
        "evidence_kind": "real_human_annotation_adjudication",
        "recovered_after_tmp_loss": False,
        "manifest_artifact": manifest_artifact,
        "manifest_artifact_sha256": manifest_sha,
        "work_orders_artifact": work_orders_artifact,
        "work_orders_artifact_sha256": work_orders_sha,
        "first_pass_submission_artifacts": [
            {
                "reviewer_id": "human_reviewer_alpha",
                "artifact": alpha_artifact,
                "artifact_sha256": alpha_sha,
            },
            {
                "reviewer_id": "human_reviewer_beta",
                "artifact": beta_artifact,
                "artifact_sha256": beta_sha,
            },
        ],
        "adjudication_artifact": adjudication_artifact,
        "adjudication_artifact_sha256": adjudication_sha,
        "confusion_matrix_artifact": confusion_artifact,
        "confusion_matrix_artifact_sha256": confusion_sha,
        "custody_receipt_artifact": custody_artifact,
        "custody_receipt_artifact_sha256": custody_sha,
        "claim_boundary": {
            "supports_human_annotation_completed_claim": True,
            "supports_human_adjudication_completed_claim": True,
            "supports_confusion_matrix_claim": True,
            "supports_custody_receipt_claim": True,
            "supports_synthetic_label_generation_claim": False,
            "supports_template_as_human_evidence_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
        },
    }


def public_source_manifest(gate_id: str, covered_hashes: list[str]) -> dict:
    sources = [
        {
            "source_id": f"public_{gate_id}_source",
            "source_url": f"https://example.org/formowl/{gate_id}/annotation.json",
            "source_type": "public_reproducible_annotation_source",
            "source_usage_role": "annotation_item_source",
            "license": "CC-BY-4.0",
            "version_or_snapshot": "2026-06-28-snapshot",
            "retrieved_at": "2026-06-28T00:00:00Z",
            "content_sha256": "abc1234567890def" * 4,
            "archive_sha256": "bcd1234567890efa" * 4,
            "derived_artifact_sha256s": sorted(set(covered_hashes)),
            "publicly_accessible": True,
            "permission_allows_research_evaluation": True,
            "non_synthetic": True,
            "raw_private_payload": False,
        }
    ]
    return public_evidence.build_manifest(
        gate_id=gate_id,
        retrieved_at="2026-06-28T00:00:00Z",
        public_sources=sources,
        covered_artifact_sha256s=covered_hashes,
    )


def add_public_evidence(packet: dict, gate_id: str, covered_hashes: list[str]) -> None:
    manifest_path, manifest_sha = write_artifact(
        "public_evidence_manifest.json",
        public_source_manifest(gate_id, covered_hashes),
    )
    packet["evidence_source_mode"] = public_evidence.PUBLIC_MODE
    packet["public_evidence_manifest_artifact"] = manifest_path
    packet["public_evidence_manifest_artifact_sha256"] = manifest_sha
    packet["claim_boundary"][public_evidence.CLAIM_FIELD] = True


def valid_llm_panel(target: str, input_hashes: list[str]) -> dict:
    panel = {
        "artifact_type": llm_panel.PANEL_ARTIFACT_TYPE,
        "panel_id": f"panel_{target}_001",
        "adjudication_target": target,
        "completed": True,
        "final_decision": "PASS",
        "human_adjudication_claimed": False,
        "input_artifact_sha256s": sorted(input_hashes),
        "rubric_sha256": LLM_PANEL_RUBRIC_SHA256,
        "specialist_subagents": [
            {
                "subagent_id": f"{specialty}_subagent",
                "specialty": specialty,
                "professional_role": llm_panel.REQUIRED_PROFESSIONAL_ROLES[specialty],
                "model_name": "codex-subagent",
                "model_version": "2026-06-28",
                "prompt_sha256": f"{index + 20:064x}",
                "rubric_sha256": LLM_PANEL_RUBRIC_SHA256,
                "run_id": f"run_{specialty}_001",
                "temperature": 0,
                "independent": True,
                "decision": "PASS",
                "blocking_findings": [],
                "reviewed_artifact_sha256s": sorted(input_hashes),
                "output_sha256": f"{index + 40:064x}",
            }
            for index, specialty in enumerate(llm_panel.REQUIRED_SPECIALTIES)
        ],
    }
    panel["panel_decision_sha256"] = llm_panel.panel_decision_sha256(panel)
    return panel


def convert_to_llm_subagent_route(packet: dict) -> dict:
    for field in (
        "first_pass_submission_artifacts",
        "adjudication_artifact",
        "adjudication_artifact_sha256",
        "confusion_matrix_artifact",
        "confusion_matrix_artifact_sha256",
        "custody_receipt_artifact",
        "custody_receipt_artifact_sha256",
    ):
        packet.pop(field, None)
    packet["artifact_id"] = "llm_subagent_annotation_results_v1"
    packet["evidence_kind"] = "four_specialist_llm_subagent_annotation_adjudication"
    packet["claim_boundary"] = {
        "supports_human_annotation_completed_claim": False,
        "supports_human_adjudication_completed_claim": False,
        "supports_llm_subagent_annotation_adjudication_completed_claim": True,
        "supports_confusion_matrix_claim": False,
        "supports_custody_receipt_claim": False,
        "supports_synthetic_label_generation_claim": False,
        "supports_template_as_human_evidence_claim": False,
        "supports_production_ready_claim": False,
        "supports_top_tier_scientific_validation_claim": False,
    }
    input_hashes = [
        packet["manifest_artifact_sha256"],
        packet["work_orders_artifact_sha256"],
    ]
    panel_artifact, panel_sha = write_artifact(
        "llm_subagent_adjudication.json",
        valid_llm_panel("annotation_adjudication_protocol", input_hashes),
    )
    packet["llm_subagent_adjudication_artifact"] = panel_artifact
    packet["llm_subagent_adjudication_artifact_sha256"] = panel_sha
    return packet


class HumanAnnotationAdjudicationValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_human_annotation_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_human_annotation_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def test_missing_packet_fails_broad_gate(self) -> None:
        report = build_report_for_test({})

        self.assertFalse(report["passed"])
        self.assertIn("human annotation results packet missing", report["blockers"])
        self.assertFalse(report["claim_boundary"]["supports_human_annotation_completed_claim"])

    def test_default_validator_rejects_templates_under_real_root(self) -> None:
        packet = valid_packet()
        for field, relative_name in (
            ("manifest_artifact", "templates/manifest.json"),
            ("work_orders_artifact", "release.template.json"),
        ):
            source = validator.safe_relative_artifact_path(
                packet[field],
                allow_test_artifacts=True,
            )
            assert source is not None
            path = validator.REAL_ARTIFACT_ROOT_PATH / relative_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            packet[field] = f"{validator.REAL_ARTIFACT_ROOT}/{relative_name}"
            packet[f"{field}_sha256"] = validator.sha256_file(path) or ""

        report = validator.build_report(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "manifest_artifact template artifacts are not accepted under "
            "inputs/human_annotation_real",
            report["blockers"],
        )
        self.assertIn(
            "work_orders_artifact template artifacts are not accepted under "
            "inputs/human_annotation_real",
            report["blockers"],
        )

    def test_default_validator_rejects_symlink_alias_to_sandbox_artifacts(self) -> None:
        packet = valid_packet()
        alias = validator.REAL_ARTIFACT_ROOT_PATH / "release_alias"
        alias.symlink_to(BASE, target_is_directory=True)
        original_prefix = f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/"
        alias_prefix = f"{validator.REAL_ARTIFACT_ROOT}/release_alias/"
        for field in (
            "manifest_artifact",
            "work_orders_artifact",
            "adjudication_artifact",
            "confusion_matrix_artifact",
            "custody_receipt_artifact",
        ):
            packet[field] = packet[field].replace(original_prefix, alias_prefix)
        for ref in packet["first_pass_submission_artifacts"]:
            ref["artifact"] = ref["artifact"].replace(original_prefix, alias_prefix)

        report = validator.build_report(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "manifest_artifact artifact symlinks are not accepted under "
            "inputs/human_annotation_real",
            report["blockers"],
        )

    def test_default_validator_rejects_symlinked_canonical_input_packet(self) -> None:
        target = validator.INPUTS / "test_human_annotation_rejected" / "canonical_target.json"
        packet_path = validator.PACKET_PATH
        original_is_symlink = packet_path.is_symlink()
        original_link_target = packet_path.readlink() if original_is_symlink else None
        original_bytes = (
            packet_path.read_bytes() if packet_path.exists() and not original_is_symlink else None
        )
        remove_path(packet_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps(valid_packet(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            packet_path.symlink_to(target)

            report = validator.build_report()

            self.assertFalse(report["passed"])
            self.assertEqual(
                report["blockers"],
                ["human annotation results packet symlink not accepted"],
            )
            self.assertFalse(report["claim_boundary"]["supports_human_annotation_completed_claim"])
        finally:
            remove_path(packet_path)
            if original_is_symlink:
                packet_path.symlink_to(original_link_target)
            elif original_bytes is not None:
                packet_path.write_bytes(original_bytes)

    def test_valid_packet_passes_validator(self) -> None:
        report = build_report_for_test(valid_packet())

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["metrics"]["first_pass_submission_artifact_count"], 2)
        self.assertTrue(report["claim_boundary"]["supports_human_adjudication_completed_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])

    def test_four_specialist_llm_subagent_route_passes_validator(self) -> None:
        report = build_report_for_test(convert_to_llm_subagent_route(valid_packet()))

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertTrue(
            report["claim_boundary"][
                "supports_llm_subagent_annotation_adjudication_completed_claim"
            ]
        )
        self.assertFalse(report["claim_boundary"]["supports_human_annotation_completed_claim"])
        self.assertFalse(report["claim_boundary"]["supports_human_adjudication_completed_claim"])

    def test_missing_llm_specialist_fails_validator(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        panel_path = validator.safe_relative_artifact_path(
            packet["llm_subagent_adjudication_artifact"],
            allow_test_artifacts=True,
        )
        assert panel_path is not None
        panel = json.loads(panel_path.read_text(encoding="utf-8"))
        panel["specialist_subagents"] = panel["specialist_subagents"][:1]
        panel["panel_decision_sha256"] = llm_panel.panel_decision_sha256(panel)
        panel_path.write_text(json.dumps(panel, indent=2, sort_keys=True) + "\n")
        packet["llm_subagent_adjudication_artifact_sha256"] = (
            validator.sha256_file(panel_path) or ""
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation four-specialist LLM panel must include exactly four subagents",
            report["blockers"],
        )

    def test_blocking_llm_specialist_fails_validator(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        panel_path = validator.safe_relative_artifact_path(
            packet["llm_subagent_adjudication_artifact"],
            allow_test_artifacts=True,
        )
        assert panel_path is not None
        panel = json.loads(panel_path.read_text(encoding="utf-8"))
        panel["specialist_subagents"][0]["decision"] = "BLOCK"
        panel["specialist_subagents"][0]["blocking_findings"] = ["annotation mismatch"]
        panel["panel_decision_sha256"] = llm_panel.panel_decision_sha256(panel)
        panel_path.write_text(json.dumps(panel, indent=2, sort_keys=True) + "\n")
        packet["llm_subagent_adjudication_artifact_sha256"] = (
            validator.sha256_file(panel_path) or ""
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation four-specialist LLM subagent decision is not PASS",
            report["blockers"],
        )

    def test_llm_route_cannot_claim_legacy_human_evidence(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        packet["claim_boundary"]["supports_human_annotation_completed_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation packet must not claim legacy human evidence "
            "when using LLM subagent adjudication: supports_human_annotation_completed_claim",
            report["blockers"],
        )

    def test_llm_route_cannot_mix_legacy_human_artifacts(self) -> None:
        source_packet = valid_packet()
        legacy_adjudication = source_packet["adjudication_artifact"]
        packet = convert_to_llm_subagent_route(source_packet)
        packet["adjudication_artifact"] = legacy_adjudication

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation packet must not mix legacy human artifacts "
            "with LLM subagent adjudication route: adjudication_artifact",
            report["blockers"],
        )

    def test_default_validator_rejects_test_fixture_artifact_paths(self) -> None:
        report = validator.build_report(valid_packet())

        self.assertFalse(report["passed"])
        self.assertIn(
            "manifest_artifact test or sandbox artifacts are not accepted under "
            "inputs/human_annotation_real",
            report["blockers"],
        )

    def test_artifact_refs_outside_real_root_fail_even_with_matching_hash(self) -> None:
        packet = valid_packet()
        artifact, digest = write_non_real_artifact(
            "manifest.json",
            {
                "artifact_type": "human_annotation_manifest_v1",
                "items": [],
            },
        )
        packet["manifest_artifact"] = artifact
        packet["manifest_artifact_sha256"] = digest
        packet["work_orders_artifact"] = "results/human_annotation_work_orders.json"
        packet["work_orders_artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "manifest_artifact path must be under inputs/human_annotation_real",
            report["blockers"],
        )
        self.assertIn(
            "work_orders_artifact path must be under inputs/human_annotation_real",
            report["blockers"],
        )

    def test_missing_second_first_pass_submission_fails(self) -> None:
        packet = valid_packet()
        packet["first_pass_submission_artifacts"] = packet["first_pass_submission_artifacts"][:1]

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "two independent first-pass human submission artifacts are not present",
            report["blockers"],
        )
        self.assertIn(
            "ann_item_invoice_001 does not have two distinct first-pass human labels",
            report["blockers"],
        )

    def test_first_pass_artifact_hash_mismatch_fails(self) -> None:
        packet = valid_packet()
        packet["first_pass_submission_artifacts"][0]["artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("first-pass submission artifact missing or hash mismatch", report["blockers"])

    def test_synthetic_first_pass_submission_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["generated_by_llm"] = True

        rewrite_first_pass_artifact(packet, 0, mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("first-pass submission is synthetic or template-derived", report["blockers"])

    def test_unsealed_first_pass_submission_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["sealed"] = False

        rewrite_first_pass_artifact(packet, 1, mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("first-pass submission is not sealed", report["blockers"])

    def test_adjudicator_must_be_distinct_from_first_pass_reviewers(self) -> None:
        packet = valid_packet()

        def mutate_work_orders(payload: dict) -> None:
            for row in payload["work_orders"]:
                if row["role"] == "adjudicator":
                    row["reviewer_id"] = "human_reviewer_alpha"
                    row["row_sha256"] = validator.row_hash(row)

        def mutate_adjudication(payload: dict) -> None:
            payload["adjudicator_id"] = "human_reviewer_alpha"
            for row in payload["rows"]:
                row["adjudicator_id"] = "human_reviewer_alpha"
                row["row_sha256"] = validator.row_hash(row)

        rewrite_packet_artifact(packet, "work_orders_artifact", mutate_work_orders)
        rewrite_packet_artifact(packet, "adjudication_artifact", mutate_adjudication)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("adjudicator is not distinct from first-pass reviewers", report["blockers"])

    def test_adjudication_must_cover_exact_disagreement_set(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"] = []

        rewrite_packet_artifact(packet, "adjudication_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "adjudication rows do not cover exactly the sealed disagreement set", report["blockers"]
        )

    def test_confusion_matrix_mismatch_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["final_label_counts"] = {"supported": 2}

        rewrite_packet_artifact(packet, "confusion_matrix_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("confusion matrix final label counts mismatch", report["blockers"])

    def test_confusion_matrix_uses_first_pass_consensus_not_manifest_consensus(self) -> None:
        packet = valid_packet()

        def mutate_invoice_label(payload: dict) -> None:
            for row in payload["rows"]:
                if row["item_id"] == "ann_item_invoice_001":
                    row["label"] = "needs_review"
                    row["row_sha256"] = validator.row_hash(row)
            payload["submission_set_sha256"] = validator.sha256_json(
                sorted(row["row_sha256"] for row in payload["rows"])
            )

        alpha_payload = rewrite_first_pass_artifact(packet, 0, mutate_invoice_label)
        beta_payload = rewrite_first_pass_artifact(packet, 1, mutate_invoice_label)
        _rebind_downstream_after_first_pass_change(packet, alpha_payload, beta_payload)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("confusion matrix final label counts mismatch", report["blockers"])

    def test_custody_receipt_mismatch_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["human_packet_complete"] = False
            payload["adjudication_artifact_sha256"] = "abcdef1234567890" * 4

        rewrite_packet_artifact(packet, "custody_receipt_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "custody receipt does not certify human packet completion", report["blockers"]
        )
        self.assertIn("custody receipt adjudication_artifact_sha256 mismatch", report["blockers"])

    def test_custody_receipt_requires_response_packet_sha256(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload.pop("response_packet_sha256", None)

        rewrite_packet_artifact(packet, "custody_receipt_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("custody receipt response_packet_sha256 missing", report["blockers"])

    def test_custody_receipt_rejects_weak_response_packet_sha256(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["response_packet_sha256"] = "0" * 64

        rewrite_packet_artifact(packet, "custody_receipt_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("custody receipt response_packet_sha256 missing", report["blockers"])

    def test_artifact_hash_mismatch_fails(self) -> None:
        packet = valid_packet()
        packet["manifest_artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("manifest_artifact missing or hash mismatch", report["blockers"])

    def test_lost_tmp_recovery_packet_fails(self) -> None:
        packet = valid_packet()
        packet["recovered_after_tmp_loss"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation packet cannot rely on lost /tmp artifacts", report["blockers"]
        )

    def test_packet_cannot_overclaim_production_or_top_tier(self) -> None:
        packet = valid_packet()
        packet["claim_boundary"]["supports_production_ready_claim"] = True
        packet["claim_boundary"]["supports_top_tier_scientific_validation_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation packet overclaims unsupported claim: supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "human annotation packet overclaims unsupported claim: supports_top_tier_scientific_validation_claim",
            report["blockers"],
        )

    def test_packet_rejects_string_truthy_or_unknown_claim_boundary_fields(self) -> None:
        packet = valid_packet()
        packet["claim_boundary"]["supports_production_ready_claim"] = "true"
        packet["claim_boundary"]["supports_goal_complete_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation packet overclaims unsupported claim: supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "human annotation packet claim boundary has unsupported fields: supports_goal_complete_claim",
            report["blockers"],
        )

    def test_packet_rejects_template_only_extra_fields(self) -> None:
        packet = valid_packet()
        packet["template_only"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human annotation results packet has unsupported fields: template_only",
            report["blockers"],
        )

    def test_public_reproducible_manifest_can_bind_llm_annotation_packet(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        add_public_evidence(
            packet,
            "annotation_adjudication_protocol",
            validator._public_evidence_hashes(packet),
        )

        report = build_report_for_test(packet)

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["evidence_source_mode"], public_evidence.PUBLIC_MODE)
        self.assertTrue(report["claim_boundary"][public_evidence.CLAIM_FIELD])


if __name__ == "__main__":
    unittest.main()
