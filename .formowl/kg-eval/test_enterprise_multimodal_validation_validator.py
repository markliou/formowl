#!/usr/bin/env python3
"""Tests for real enterprise multimodal validation evidence intake."""

from __future__ import annotations

import json
import shutil
import unittest

import enterprise_multimodal_validation_validator as validator
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
    path = validator.INPUTS / "test_enterprise_multimodal_rejected" / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"inputs/test_enterprise_multimodal_rejected/{relative_name}", validator.sha256_file(
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


def rewrite_validation_artifact(packet: dict, index: int, mutate) -> dict:
    ref = packet["validation_artifacts"][index]
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


def rebind_after_validation_change(packet: dict) -> None:
    validation_hashes = sorted(ref["artifact_sha256"] for ref in packet["validation_artifacts"])
    all_rows = []
    for ref in packet["validation_artifacts"]:
        path = validator.safe_relative_artifact_path(
            ref["artifact"],
            allow_test_artifacts=True,
        )
        assert path is not None
        payload = json.loads(path.read_text(encoding="utf-8"))
        all_rows.extend(payload["rows"])

    def mutate_adjudication(payload: dict) -> None:
        payload["validation_artifact_sha256s"] = validation_hashes
        payload["rows"] = [
            validator.with_row_hash(
                {
                    "adjudication_id": f"adj_{row['validation_id']}",
                    "validation_id": row["validation_id"],
                    "validation_row_sha256": row["row_sha256"],
                    "modality": row["modality"],
                    "final_label": "accepted",
                }
            )
            for row in all_rows
        ]

    rewrite_packet_artifact(packet, "human_adjudication_artifact", mutate_adjudication)

    def mutate_business(payload: dict) -> None:
        payload["adjudication_artifact_sha256"] = packet["human_adjudication_artifact_sha256"]

    rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate_business)


def valid_packet() -> dict:
    source_rows = []
    source_by_modality = {}
    for index, modality in enumerate(validator.REQUIRED_MODALITIES):
        row = validator.with_row_hash(
            {
                "source_id": f"src_{modality}_001",
                "modality": modality,
                "asset_id": f"asset_{modality}_001",
                "asset_sha256": f"{index + 1:064x}",
                "formowl_locator": f"formowl://asset/asset_{modality}_001",
                "permission_scope_id": "workspace_finance_ops",
                "real_enterprise_data": True,
                "text_proxy_only": False,
                "raw_path_exposed": False,
            }
        )
        source_rows.append(row)
        source_by_modality[modality] = row
    manifest = {
        "artifact_type": "enterprise_multimodal_pilot_manifest_v1",
        "real_enterprise_pilot": True,
        "synthetic_or_demo": False,
        "source_artifacts": source_rows,
    }
    manifest_artifact, manifest_sha = write_artifact("pilot_manifest.json", manifest)

    validation_refs = []
    validation_rows = []
    for modality in validator.REQUIRED_MODALITIES:
        source = source_by_modality[modality]
        row = validator.with_row_hash(
            {
                "validation_id": f"val_{modality}_001",
                "modality": modality,
                "source_id": source["source_id"],
                "source_asset_sha256": source["asset_sha256"],
                "observation_id": f"obs_{modality}_001",
                "extractor_run_id": f"run_{modality}_001",
                "candidate_id": f"cand_{modality}_001",
                "task": f"{modality}_semantic_validation",
                "human_adjudicated": True,
            }
        )
        artifact = {
            "artifact_type": "enterprise_multimodal_validation_rows_v1",
            "modality": modality,
            "rows": [row],
        }
        artifact_path, artifact_sha = write_artifact(f"validation_{modality}.json", artifact)
        validation_refs.append(
            {"modality": modality, "artifact": artifact_path, "artifact_sha256": artifact_sha}
        )
        validation_rows.append(row)

    adjudication = {
        "artifact_type": "enterprise_multimodal_human_adjudication_v1",
        "completed": True,
        "reviewer_id": "human_multimodal_reviewer",
        "reviewer_type": "human",
        "synthetic_or_agent_generated": False,
        "validation_artifact_sha256s": sorted(ref["artifact_sha256"] for ref in validation_refs),
        "rows": [
            validator.with_row_hash(
                {
                    "adjudication_id": f"adj_{row['validation_id']}",
                    "validation_id": row["validation_id"],
                    "validation_row_sha256": row["row_sha256"],
                    "modality": row["modality"],
                    "final_label": "accepted",
                }
            )
            for row in validation_rows
        ],
    }
    adjudication_artifact, adjudication_sha = write_artifact(
        "human_adjudication.json", adjudication
    )

    decision_review = {
        "artifact_type": "enterprise_business_decision_review_v1",
        "human_reviewed": True,
        "autonomous_business_judgment": False,
        "financial_advice_or_execution": False,
        "adjudication_artifact_sha256": adjudication_sha,
        "decision_rows": [
            validator.with_row_hash(
                {
                    "decision_candidate_id": "decision_invoice_payment_review",
                    "source_validation_ids": [row["validation_id"] for row in validation_rows],
                    "requires_human_review": True,
                    "autonomous_business_judgment": False,
                }
            )
        ],
    }
    decision_artifact, decision_sha = write_artifact(
        "business_decision_review.json", decision_review
    )

    permission_probe = {
        "artifact_type": "enterprise_multimodal_permission_probe_v1",
        "completed": True,
        "source_ids": sorted(row["source_id"] for row in source_rows),
        "revoked_grant_content_denied": True,
        "private_content_not_returned": True,
        "raw_asset_access_denied": True,
        "entity_match_does_not_grant_access": True,
        "cross_modal_private_leak_count": 0,
        "raw_asset_access_count": 0,
    }
    permission_artifact, permission_sha = write_artifact("permission_probe.json", permission_probe)

    return {
        "artifact_id": "enterprise_multimodal_validation_packet_v1",
        "evidence_kind": "real_enterprise_multimodal_validation",
        "recovered_after_tmp_loss": False,
        "pilot_manifest_artifact": manifest_artifact,
        "pilot_manifest_artifact_sha256": manifest_sha,
        "validation_artifacts": validation_refs,
        "human_adjudication_artifact": adjudication_artifact,
        "human_adjudication_artifact_sha256": adjudication_sha,
        "business_decision_review_artifact": decision_artifact,
        "business_decision_review_artifact_sha256": decision_sha,
        "permission_probe_artifact": permission_artifact,
        "permission_probe_artifact_sha256": permission_sha,
        "claim_boundary": {
            "supports_real_enterprise_multimodal_claim": True,
            "supports_multimodal_human_adjudication_completed_claim": True,
            "supports_cross_modal_permission_probe_claim": True,
            "supports_business_decision_review_claim": True,
            "supports_financial_advice_or_autonomous_business_judgment_claim": False,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_raw_asset_access_claim": False,
        },
    }


def public_source_manifest(gate_id: str, covered_hashes: list[str]) -> dict:
    sources = [
        {
            "source_id": f"public_{gate_id}_source",
            "source_url": f"https://example.org/formowl/{gate_id}/multimodal.json",
            "source_type": "public_reproducible_multimodal_corpus",
            "source_usage_role": "multimodal_validation_source",
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
    packet.pop("human_adjudication_artifact", None)
    packet.pop("human_adjudication_artifact_sha256", None)
    for ref in packet["validation_artifacts"]:
        path = validator.safe_relative_artifact_path(
            ref["artifact"],
            allow_test_artifacts=True,
        )
        assert path is not None
        artifact = json.loads(path.read_text(encoding="utf-8"))
        for row in artifact["rows"]:
            row.pop("human_adjudicated", None)
            row["llm_subagent_adjudicated"] = True
            row["row_sha256"] = validator.row_hash(row)
        path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n")
        ref["artifact_sha256"] = validator.sha256_file(path) or ""

    input_hashes = [
        packet["pilot_manifest_artifact_sha256"],
        *[ref["artifact_sha256"] for ref in packet["validation_artifacts"]],
    ]
    panel_artifact, panel_sha = write_artifact(
        "llm_subagent_adjudication.json",
        valid_llm_panel("multimodal_semantic_validation", input_hashes),
    )
    packet["llm_subagent_adjudication_artifact"] = panel_artifact
    packet["llm_subagent_adjudication_artifact_sha256"] = panel_sha

    def mutate_business(payload: dict) -> None:
        payload.pop("human_reviewed", None)
        payload["llm_subagent_reviewed"] = True
        payload["adjudication_artifact_sha256"] = panel_sha

    rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate_business)
    packet["claim_boundary"]["supports_multimodal_human_adjudication_completed_claim"] = False
    packet["claim_boundary"]["supports_multimodal_llm_subagent_adjudication_completed_claim"] = True
    return packet


class EnterpriseMultimodalValidationValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_enterprise_multimodal_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_enterprise_multimodal_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def test_missing_packet_fails_broad_gate(self) -> None:
        report = build_report_for_test({})

        self.assertFalse(report["passed"])
        self.assertIn("enterprise multimodal validation packet missing", report["blockers"])
        self.assertFalse(report["claim_boundary"]["supports_real_enterprise_multimodal_claim"])

    def test_default_validator_rejects_templates_under_real_root(self) -> None:
        packet = valid_packet()
        for field, relative_name in (
            ("pilot_manifest_artifact", "templates/pilot_manifest.json"),
            ("human_adjudication_artifact", "release.template.json"),
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
            "pilot_manifest_artifact template artifacts are not accepted under "
            "inputs/enterprise_multimodal_real",
            report["blockers"],
        )
        self.assertIn(
            "human_adjudication_artifact template artifacts are not accepted under "
            "inputs/enterprise_multimodal_real",
            report["blockers"],
        )

    def test_default_validator_rejects_symlink_alias_to_sandbox_artifacts(self) -> None:
        packet = valid_packet()
        alias = validator.REAL_ARTIFACT_ROOT_PATH / "release_alias"
        alias.symlink_to(BASE, target_is_directory=True)
        original_prefix = f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/"
        alias_prefix = f"{validator.REAL_ARTIFACT_ROOT}/release_alias/"
        for field in (
            "pilot_manifest_artifact",
            "human_adjudication_artifact",
            "business_decision_review_artifact",
            "permission_probe_artifact",
        ):
            packet[field] = packet[field].replace(original_prefix, alias_prefix)
        for ref in packet["validation_artifacts"]:
            ref["artifact"] = ref["artifact"].replace(original_prefix, alias_prefix)

        report = validator.build_report(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "pilot_manifest_artifact artifact symlinks are not accepted under "
            "inputs/enterprise_multimodal_real",
            report["blockers"],
        )

    def test_valid_packet_passes_validator(self) -> None:
        report = build_report_for_test(valid_packet())

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["metrics"]["validation_artifact_count"], 4)
        self.assertTrue(
            report["claim_boundary"]["supports_multimodal_human_adjudication_completed_claim"]
        )
        self.assertFalse(
            report["claim_boundary"][
                "supports_financial_advice_or_autonomous_business_judgment_claim"
            ]
        )

    def test_four_specialist_llm_subagent_route_passes_validator(self) -> None:
        report = build_report_for_test(convert_to_llm_subagent_route(valid_packet()))

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertTrue(
            report["claim_boundary"][
                "supports_multimodal_llm_subagent_adjudication_completed_claim"
            ]
        )
        self.assertFalse(
            report["claim_boundary"]["supports_multimodal_human_adjudication_completed_claim"]
        )

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
            "enterprise multimodal four-specialist LLM panel must include exactly four subagents",
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
        panel["specialist_subagents"][0]["blocking_findings"] = ["missing modality"]
        panel["panel_decision_sha256"] = llm_panel.panel_decision_sha256(panel)
        panel_path.write_text(json.dumps(panel, indent=2, sort_keys=True) + "\n")
        packet["llm_subagent_adjudication_artifact_sha256"] = (
            validator.sha256_file(panel_path) or ""
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal four-specialist LLM subagent decision is not PASS",
            report["blockers"],
        )

    def test_llm_route_cannot_claim_human_adjudication(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        packet["claim_boundary"]["supports_multimodal_human_adjudication_completed_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal packet must not claim human adjudication "
            "when using LLM subagent adjudication",
            report["blockers"],
        )

    def test_llm_route_rejects_human_adjudicated_validation_rows(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())

        def mutate(payload: dict) -> None:
            payload["rows"][0]["human_adjudicated"] = True
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_validation_artifact(packet, 0, mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation row must not claim human adjudication on LLM route",
            report["blockers"],
        )

    def test_llm_route_rejects_human_reviewed_business_review(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())

        def mutate(payload: dict) -> None:
            payload["human_reviewed"] = True

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise business decision review must not claim human review on LLM route",
            report["blockers"],
        )

    def test_llm_route_cannot_mix_human_adjudication_artifact(self) -> None:
        source_packet = valid_packet()
        legacy_adjudication = source_packet["human_adjudication_artifact"]
        packet = convert_to_llm_subagent_route(source_packet)
        packet["human_adjudication_artifact"] = legacy_adjudication

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal packet must not mix human and LLM adjudication routes",
            report["blockers"],
        )

    def test_default_validator_rejects_test_fixture_artifact_paths(self) -> None:
        report = validator.build_report(valid_packet())

        self.assertFalse(report["passed"])
        self.assertIn(
            "pilot_manifest_artifact test or sandbox artifacts are not accepted under "
            "inputs/enterprise_multimodal_real",
            report["blockers"],
        )

    def test_artifact_refs_outside_real_root_fail_even_with_matching_hash(self) -> None:
        packet = valid_packet()
        artifact, digest = write_non_real_artifact(
            "pilot_manifest.json",
            {
                "artifact_type": "enterprise_multimodal_pilot_manifest_v1",
                "source_artifacts": [],
            },
        )
        packet["pilot_manifest_artifact"] = artifact
        packet["pilot_manifest_artifact_sha256"] = digest
        packet["validation_artifacts"][0]["artifact"] = "results/enterprise_validation_rows.json"
        packet["validation_artifacts"][0]["artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "pilot_manifest_artifact path must be under inputs/enterprise_multimodal_real",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal validation artifact path must be under "
            "inputs/enterprise_multimodal_real",
            report["blockers"],
        )

    def test_missing_required_modality_fails(self) -> None:
        packet = valid_packet()
        packet["validation_artifacts"] = [
            ref for ref in packet["validation_artifacts"] if ref["modality"] != "video_ocr"
        ]

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation artifacts missing modalities: video_ocr",
            report["blockers"],
        )

    def test_validation_artifact_reference_raw_internal_field_fails(self) -> None:
        packet = valid_packet()
        packet["validation_artifacts"][0]["raw_path"] = "/mnt/nas/source.wav"

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation artifact reference has unsupported fields: raw_path",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal validation artifact reference contains raw/internal value: raw_path",
            report["blockers"],
        )

    def test_text_proxy_or_raw_path_source_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["source_artifacts"][0]["text_proxy_only"] = True
            payload["source_artifacts"][0]["raw_path_exposed"] = True
            payload["source_artifacts"][0]["row_sha256"] = validator.row_hash(
                payload["source_artifacts"][0]
            )

        rewrite_packet_artifact(packet, "pilot_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("src_spreadsheet_001 is text-proxy-only", report["blockers"])
        self.assertIn("src_spreadsheet_001 exposes raw path", report["blockers"])

    def test_manifest_raw_internal_source_field_fails_even_when_flag_is_false(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["source_artifacts"][0]["raw_path"] = "/mnt/nas/finance.xlsx"
            payload["source_artifacts"][0]["raw_path_exposed"] = False
            payload["source_artifacts"][0]["row_sha256"] = validator.row_hash(
                payload["source_artifacts"][0]
            )

        rewrite_packet_artifact(packet, "pilot_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "src_spreadsheet_001 contains forbidden raw/internal source field: raw_path",
            report["blockers"],
        )

    def test_manifest_formowl_locator_must_match_asset_id(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["source_artifacts"][0]["formowl_locator"] = "formowl://asset/other_asset"
            payload["source_artifacts"][0]["row_sha256"] = validator.row_hash(
                payload["source_artifacts"][0]
            )

        rewrite_packet_artifact(packet, "pilot_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "src_spreadsheet_001 FormOwl asset locator does not match asset_id", report["blockers"]
        )

    def test_manifest_source_row_synthetic_hidden_field_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["source_artifacts"][0]["synthetic_or_demo"] = True
            payload["source_artifacts"][0]["row_sha256"] = validator.row_hash(
                payload["source_artifacts"][0]
            )

        rewrite_packet_artifact(packet, "pilot_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal source artifact row has unsupported fields: synthetic_or_demo",
            report["blockers"],
        )

    def test_manifest_source_row_rejects_uppercase_raw_uri_value(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["source_artifacts"][0]["permission_scope_id"] = "S3://finance-bucket/source.wav"
            payload["source_artifacts"][0]["row_sha256"] = validator.row_hash(
                payload["source_artifacts"][0]
            )

        rewrite_packet_artifact(packet, "pilot_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "src_spreadsheet_001 contains forbidden raw/internal source value: permission_scope_id",
            report["blockers"],
        )

    def test_validation_source_hash_mismatch_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["source_asset_sha256"] = "abcdef1234567890" * 4
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_validation_artifact(packet, 0, mutate)
        rebind_after_validation_change(packet)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation source asset hash mismatch", report["blockers"]
        )

    def test_validation_id_must_be_non_empty_string(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["validation_id"] = None
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_validation_artifact(packet, 0, mutate)
        rebind_after_validation_change(packet)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation id missing or malformed", report["blockers"]
        )

    def test_validation_row_raw_internal_field_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["raw_path"] = "/mnt/nas/source.wav"
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_validation_artifact(packet, 0, mutate)
        rebind_after_validation_change(packet)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation row has unsupported fields: raw_path",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal validation row contains raw/internal value: raw_path",
            report["blockers"],
        )

    def test_validation_artifact_top_level_hidden_raw_or_synthetic_field_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["synthetic_or_agent_generated"] = True
            payload["raw_path"] = "/mnt/nas/source.wav"

        rewrite_validation_artifact(packet, 0, mutate)
        rebind_after_validation_change(packet)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation artifact has unsupported fields: raw_path, synthetic_or_agent_generated",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal validation artifact contains raw/internal value: raw_path",
            report["blockers"],
        )

    def test_non_human_adjudication_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["reviewer_type"] = "agent"
            payload["synthetic_or_agent_generated"] = True

        rewrite_packet_artifact(packet, "human_adjudication_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("enterprise multimodal adjudicator is not human", report["blockers"])
        self.assertIn(
            "enterprise multimodal adjudication is synthetic or agent-generated", report["blockers"]
        )

    def test_adjudication_must_cover_all_validation_rows(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"] = payload["rows"][:1]

        rewrite_packet_artifact(packet, "human_adjudication_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal adjudication does not cover every validation row",
            report["blockers"],
        )

    def test_duplicate_conflicting_adjudication_row_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            duplicate = dict(payload["rows"][0])
            duplicate["adjudication_id"] = f"{duplicate['adjudication_id']}_duplicate"
            duplicate["final_label"] = "rejected"
            duplicate["row_sha256"] = validator.row_hash(duplicate)
            payload["rows"].append(duplicate)

        rewrite_packet_artifact(packet, "human_adjudication_artifact", mutate)

        def mutate_business(payload: dict) -> None:
            payload["adjudication_artifact_sha256"] = packet["human_adjudication_artifact_sha256"]

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate_business)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal adjudication duplicate validation row", report["blockers"]
        )

    def test_adjudication_row_synthetic_or_raw_internal_field_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["synthetic_or_agent_generated"] = True
            payload["rows"][0]["raw_path"] = "/mnt/nas/adjudication.csv"
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "human_adjudication_artifact", mutate)

        def mutate_business(payload: dict) -> None:
            payload["adjudication_artifact_sha256"] = packet["human_adjudication_artifact_sha256"]

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate_business)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal adjudication row has unsupported fields: raw_path, synthetic_or_agent_generated",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal adjudication row contains raw/internal value: raw_path",
            report["blockers"],
        )

    def test_business_decision_autonomous_or_financial_advice_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["autonomous_business_judgment"] = True
            payload["financial_advice_or_execution"] = True
            payload["decision_rows"][0]["autonomous_business_judgment"] = True
            payload["decision_rows"][0]["row_sha256"] = validator.row_hash(
                payload["decision_rows"][0]
            )

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise business decision review allows autonomous judgment", report["blockers"]
        )
        self.assertIn(
            "enterprise business decision review claims financial advice or execution",
            report["blockers"],
        )
        self.assertIn(
            "enterprise business decision row allows autonomous judgment", report["blockers"]
        )

    def test_business_decision_row_financial_advice_field_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["decision_rows"][0]["financial_advice_or_execution"] = True
            payload["decision_rows"][0]["row_sha256"] = validator.row_hash(
                payload["decision_rows"][0]
            )

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise business decision row claims financial advice or execution",
            report["blockers"],
        )

    def test_business_decision_row_raw_internal_value_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["decision_rows"][0]["decision_candidate_id"] = "/mnt/nas/approval.csv"
            payload["decision_rows"][0]["row_sha256"] = validator.row_hash(
                payload["decision_rows"][0]
            )

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise business decision row contains raw/internal value: decision_candidate_id",
            report["blockers"],
        )

    def test_business_decision_review_must_cover_all_validation_rows(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["decision_rows"][0]["source_validation_ids"] = [
                payload["decision_rows"][0]["source_validation_ids"][0]
            ]
            payload["decision_rows"][0]["row_sha256"] = validator.row_hash(
                payload["decision_rows"][0]
            )

        rewrite_packet_artifact(packet, "business_decision_review_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise business decision review does not cover every validation row",
            report["blockers"],
        )

    def test_permission_probe_leak_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["private_content_not_returned"] = False
            payload["cross_modal_private_leak_count"] = 1
            payload["raw_asset_access_count"] = 1

        rewrite_packet_artifact(packet, "permission_probe_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal permission probe failed or missing: private_content_not_returned",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal permission probe leaked private content", report["blockers"]
        )
        self.assertIn(
            "enterprise multimodal permission probe exposed raw asset access", report["blockers"]
        )

    def test_permission_probe_positive_revoked_or_entity_match_counts_fail(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["revoked_grant_visible_count"] = 1
            payload["entity_match_access_count"] = 1

        rewrite_packet_artifact(packet, "permission_probe_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal permission probe has positive leak count: revoked_grant_visible_count",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal permission probe has positive leak count: entity_match_access_count",
            report["blockers"],
        )

    def test_packet_cannot_overclaim_production_or_top_tier(self) -> None:
        packet = valid_packet()
        packet["claim_boundary"]["supports_production_ready_claim"] = True
        packet["claim_boundary"]["supports_top_tier_scientific_validation_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal packet overclaims unsupported claim: supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal packet overclaims unsupported claim: supports_top_tier_scientific_validation_claim",
            report["blockers"],
        )

    def test_packet_rejects_malformed_truthy_negative_claims(self) -> None:
        packet = valid_packet()
        packet["claim_boundary"]["supports_production_ready_claim"] = "true"
        packet["claim_boundary"]["supports_raw_asset_access_claim"] = 1

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal packet overclaims unsupported claim: supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal packet overclaims unsupported claim: supports_raw_asset_access_claim",
            report["blockers"],
        )

    def test_lost_tmp_recovery_packet_fails(self) -> None:
        packet = valid_packet()
        packet["recovered_after_tmp_loss"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal packet cannot rely on lost /tmp artifacts", report["blockers"]
        )

    def test_malformed_truthy_lost_tmp_recovery_flag_fails(self) -> None:
        packet = valid_packet()
        packet["recovered_after_tmp_loss"] = "true"

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal packet cannot rely on lost /tmp artifacts", report["blockers"]
        )

    def test_packet_envelope_or_extra_claim_boundary_overclaim_fails(self) -> None:
        packet = valid_packet()
        packet["raw_path"] = "/mnt/nas/source.wav"
        packet["claim_boundary"]["supports_unreviewed_business_judgment_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "enterprise multimodal validation packet has unsupported fields: raw_path",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal validation packet contains raw/internal value: raw_path",
            report["blockers"],
        )
        self.assertIn(
            "enterprise multimodal packet claim boundary has unsupported fields: supports_unreviewed_business_judgment_claim",
            report["blockers"],
        )

    def test_public_reproducible_manifest_can_bind_llm_multimodal_packet(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        add_public_evidence(
            packet,
            "multimodal_semantic_validation",
            validator._public_evidence_hashes(packet),
        )

        report = build_report_for_test(packet)

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["evidence_source_mode"], public_evidence.PUBLIC_MODE)
        self.assertTrue(report["claim_boundary"][public_evidence.CLAIM_FIELD])


if __name__ == "__main__":
    unittest.main()
