#!/usr/bin/env python3
"""Tests for production adapter path evidence intake."""

from __future__ import annotations

import json
import shutil
import unittest

import llm_subagent_adjudication as llm_panel
import production_adapter_path_validator as validator
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
    path = validator.INPUTS / "test_production_adapter_rejected" / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"inputs/test_production_adapter_rejected/{relative_name}", validator.sha256_file(
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


def rewrite_adapter_artifact(packet: dict, index: int, mutate) -> dict:
    ref = packet["adapter_artifacts"][index]
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


def valid_packet() -> dict:
    deployment_id = "deploy_prod_adapter_001"
    manifest = {
        "artifact_type": "production_adapter_deployment_manifest_v1",
        "deployment_id": deployment_id,
        "environment_id": "closed_beta_prod_like",
        "non_synthetic_deployment": True,
        "synthetic_or_demo": False,
        "release_artifact_sha256": f"{1:064x}",
        "container_image_digest_sha256": f"{2:064x}",
        "migration_manifest_sha256": f"{3:064x}",
        "adapter_stack_sha256": f"{4:064x}",
        "deployment_approved_by_human": True,
        "raw_path_exposed": False,
    }

    adapter_refs = []
    adapter_artifacts_by_component = {}
    adapter_hashes_by_component = {}
    for index, component_id in enumerate(validator.REQUIRED_COMPONENTS):
        artifact = {
            "artifact_type": "production_adapter_component_artifact_v1",
            "component_id": component_id,
            "component_kind": "adapter_boundary",
            "deployment_id": deployment_id,
            "non_synthetic_deployment": True,
            "synthetic_or_demo": False,
            "package_or_image_sha256": f"{index + 10:064x}",
            "config_sha256": f"{index + 30:064x}",
            "policy_sha256": f"{index + 50:064x}",
            "permission_filter_enabled": True,
            "raw_path_exposed": False,
            "canonical_write_enabled": False,
        }
        path, digest = write_artifact(f"adapter_{component_id}.json", artifact)
        adapter_refs.append(
            {"component_id": component_id, "artifact": path, "artifact_sha256": digest}
        )
        adapter_artifacts_by_component[component_id] = artifact
        adapter_hashes_by_component[component_id] = digest

    manifest["adapter_stack_sha256"] = validator.adapter_stack_digest(
        adapter_artifacts_by_component,
        adapter_hashes_by_component,
    )
    manifest_artifact, manifest_sha = write_artifact("deployment_manifest.json", manifest)

    label_rows = []
    for index, adapter_id in enumerate(validator.FALSE_MERGE_ADAPTERS):
        label_rows.append(
            validator.with_row_hash(
                {
                    "label_id": f"label_{adapter_id}",
                    "adapter_component_id": adapter_id,
                    "candidate_pair_id": f"pair_{adapter_id}",
                    "human_reviewer_id": f"human_reviewer_{index}",
                    "reviewer_type": "human",
                    "human_reviewed": True,
                    "false_merge_label": True,
                    "candidate_pair_sha256": f"{index + 70:064x}",
                    "source_candidate_sha256s": [f"{index + 80:064x}", f"{index + 90:064x}"],
                }
            )
        )
    labels = {
        "artifact_type": "production_adapter_false_merge_labels_v1",
        "completed": True,
        "reviewer_type": "human",
        "synthetic_or_agent_generated": False,
        "deployment_id": deployment_id,
        "rows": label_rows,
    }
    labels_artifact, labels_sha = write_artifact("false_merge_labels.json", labels)

    request_id = "request_prod_adapter_001"
    policy_id = "production_adapter_policy_001"
    audit_rows = []
    for index, action in enumerate(validator.REQUIRED_AUDIT_ACTIONS):
        deny = action in {
            "revoked_grant_blocks_content",
            "private_candidate_redacted",
            "entity_match_without_grant_denied",
            "raw_asset_read_guard_rejected",
            "canonical_merge_guard_rejected",
        }
        row = {
            "event_id": f"event_{index:02d}_{action}",
            "sequence": index,
            "action": action,
            "deployment_id": deployment_id,
            "request_id": request_id,
            "actor_id": "actor_ops_reviewer",
            "resource_ref": "formowl://graph-view/prod-adapter",
            "policy_id": policy_id,
            "decision": "deny" if deny else "allow",
            "event_sha256": f"{index + 100:064x}",
        }
        if deny:
            row["denial_reason"] = f"{action}_guard"
        if action == "revoked_grant_blocks_content":
            row["grant_state"] = "revoked"
        if action == "wiki_projection_draft_not_published":
            row["published"] = False
        if action == "rollback_smoke_completed":
            row["rollback_verified"] = True
        audit_rows.append(validator.with_row_hash(row))
    audit = {
        "artifact_type": "production_adapter_audit_trail_v1",
        "deployment_id": deployment_id,
        "policy_id": policy_id,
        "rows": audit_rows,
    }
    audit_artifact, audit_sha = write_artifact("audit_trail.json", audit)

    permission_probe = {
        "artifact_type": "production_adapter_permission_probe_v1",
        "completed": True,
        "deployment_id": deployment_id,
        "component_ids": sorted(validator.REQUIRED_COMPONENTS),
        "revoked_grant_content_denied": True,
        "private_content_not_returned": True,
        "raw_asset_access_denied": True,
        "entity_match_does_not_grant_access": True,
        "canonical_merge_without_review_denied": True,
        "private_leak_count": 0,
        "raw_asset_access_count": 0,
        "entity_match_access_count": 0,
        "canonical_write_count": 0,
    }
    permission_artifact, permission_sha = write_artifact("permission_probe.json", permission_probe)

    rollback = {
        "artifact_type": "production_adapter_rollback_smoke_v1",
        "completed": True,
        "deployment_id": deployment_id,
        "non_synthetic_deployment": True,
        "migration_rollback_verified": True,
        "partial_failure_rollback_verified": True,
        "audit_append_only_verified": True,
        "idempotent_retry_verified": True,
        "rollback_run_sha256": "f" * 63 + "1",
    }
    rollback_artifact, rollback_sha = write_artifact("rollback_smoke.json", rollback)

    return {
        "artifact_id": "production_adapter_evidence_packet_v1",
        "evidence_kind": "non_synthetic_production_adapter_validation",
        "recovered_after_tmp_loss": False,
        "deployment_manifest_artifact": manifest_artifact,
        "deployment_manifest_artifact_sha256": manifest_sha,
        "adapter_artifacts": adapter_refs,
        "human_false_merge_label_artifact": labels_artifact,
        "human_false_merge_label_artifact_sha256": labels_sha,
        "audit_trail_artifact": audit_artifact,
        "audit_trail_artifact_sha256": audit_sha,
        "permission_probe_artifact": permission_artifact,
        "permission_probe_artifact_sha256": permission_sha,
        "rollback_smoke_artifact": rollback_artifact,
        "rollback_smoke_artifact_sha256": rollback_sha,
        "claim_boundary": {
            "supports_production_adapter_paths_claim": True,
            "supports_non_synthetic_deployment_claim": True,
            "supports_human_reviewed_false_merge_labels_claim": True,
            "supports_permission_probe_claim": True,
            "supports_rollback_smoke_claim": True,
            "supports_full_product_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_canonical_write_claim": False,
            "supports_raw_access_claim": False,
        },
    }


def public_source_manifest(gate_id: str, covered_hashes: list[str]) -> dict:
    sources = [
        {
            "source_id": f"public_{gate_id}_source",
            "source_url": f"https://example.org/formowl/{gate_id}/adapter.json",
            "source_type": "public_reproducible_adapter_release",
            "source_usage_role": "production_adapter_evidence_source",
            "license": "Apache-2.0",
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
    def mutate_manifest(payload: dict) -> None:
        payload["deployment_approved_by_human"] = False
        payload["deployment_approved_by_llm_subagent_panel"] = True

    rewrite_packet_artifact(packet, "deployment_manifest_artifact", mutate_manifest)

    panel_id = "panel_production_adapter_paths_001"

    def mutate_labels(payload: dict) -> None:
        payload["reviewer_type"] = "four_specialist_llm_subagent_panel"
        payload["llm_subagent_panel_reviewed"] = True
        for row in payload["rows"]:
            row.pop("human_reviewer_id", None)
            row.pop("human_reviewed", None)
            row["llm_subagent_panel_id"] = panel_id
            row["reviewer_type"] = "four_specialist_llm_subagent_panel"
            row["llm_subagent_reviewed"] = True
            row["row_sha256"] = validator.row_hash(row)

    rewrite_packet_artifact(packet, "human_false_merge_label_artifact", mutate_labels)

    input_hashes = [
        packet["deployment_manifest_artifact_sha256"],
        *[ref["artifact_sha256"] for ref in packet["adapter_artifacts"]],
        packet["human_false_merge_label_artifact_sha256"],
        packet["audit_trail_artifact_sha256"],
        packet["permission_probe_artifact_sha256"],
        packet["rollback_smoke_artifact_sha256"],
    ]
    panel = valid_llm_panel("production_adapter_paths", input_hashes)
    panel["panel_id"] = panel_id
    panel["panel_decision_sha256"] = llm_panel.panel_decision_sha256(panel)
    panel_artifact, panel_sha = write_artifact("llm_subagent_adjudication.json", panel)
    packet["llm_subagent_adjudication_artifact"] = panel_artifact
    packet["llm_subagent_adjudication_artifact_sha256"] = panel_sha
    packet["claim_boundary"]["supports_human_reviewed_false_merge_labels_claim"] = False
    packet["claim_boundary"]["supports_llm_subagent_deployment_approval_claim"] = True
    packet["claim_boundary"]["supports_llm_subagent_reviewed_false_merge_labels_claim"] = True
    return packet


class ProductionAdapterPathValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_production_adapter_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_production_adapter_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def test_missing_packet_fails_broad_gate(self) -> None:
        report = build_report_for_test({})

        self.assertFalse(report["passed"])
        self.assertIn("production adapter evidence packet missing", report["blockers"])
        self.assertFalse(report["claim_boundary"]["supports_production_adapter_paths_claim"])

    def test_default_validator_rejects_templates_under_real_root(self) -> None:
        packet = valid_packet()
        for field, relative_name in (
            ("deployment_manifest_artifact", "templates/deployment_manifest.json"),
            ("audit_trail_artifact", "release.template.json"),
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
            "deployment_manifest_artifact template artifacts are not accepted under "
            "inputs/production_adapter_real",
            report["blockers"],
        )
        self.assertIn(
            "audit_trail_artifact template artifacts are not accepted under "
            "inputs/production_adapter_real",
            report["blockers"],
        )

    def test_default_validator_rejects_symlink_alias_to_sandbox_artifacts(self) -> None:
        packet = valid_packet()
        alias = validator.REAL_ARTIFACT_ROOT_PATH / "release_alias"
        alias.symlink_to(BASE, target_is_directory=True)
        original_prefix = f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/"
        alias_prefix = f"{validator.REAL_ARTIFACT_ROOT}/release_alias/"
        for field in (
            "deployment_manifest_artifact",
            "human_false_merge_label_artifact",
            "audit_trail_artifact",
            "permission_probe_artifact",
            "rollback_smoke_artifact",
        ):
            packet[field] = packet[field].replace(original_prefix, alias_prefix)
        for ref in packet["adapter_artifacts"]:
            ref["artifact"] = ref["artifact"].replace(original_prefix, alias_prefix)

        report = validator.build_report(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "deployment_manifest_artifact artifact symlinks are not accepted under "
            "inputs/production_adapter_real",
            report["blockers"],
        )

    def test_valid_packet_passes_validator(self) -> None:
        report = build_report_for_test(valid_packet())

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(
            report["metrics"]["adapter_artifact_count"], len(validator.REQUIRED_COMPONENTS)
        )
        self.assertTrue(
            report["claim_boundary"]["supports_human_reviewed_false_merge_labels_claim"]
        )
        self.assertFalse(report["claim_boundary"]["supports_full_product_production_ready_claim"])

    def test_four_specialist_llm_subagent_route_passes_validator(self) -> None:
        report = build_report_for_test(convert_to_llm_subagent_route(valid_packet()))

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertTrue(report["claim_boundary"]["supports_llm_subagent_deployment_approval_claim"])
        self.assertTrue(
            report["claim_boundary"]["supports_llm_subagent_reviewed_false_merge_labels_claim"]
        )
        self.assertFalse(
            report["claim_boundary"]["supports_human_reviewed_false_merge_labels_claim"]
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
            "production adapter four-specialist LLM panel must include exactly four subagents",
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
        panel["specialist_subagents"][0]["blocking_findings"] = ["deployment gap"]
        panel["panel_decision_sha256"] = llm_panel.panel_decision_sha256(panel)
        panel_path.write_text(json.dumps(panel, indent=2, sort_keys=True) + "\n")
        packet["llm_subagent_adjudication_artifact_sha256"] = (
            validator.sha256_file(panel_path) or ""
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter four-specialist LLM subagent decision is not PASS",
            report["blockers"],
        )

    def test_llm_route_cannot_claim_human_false_merge_review(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        packet["claim_boundary"]["supports_human_reviewed_false_merge_labels_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter packet must not claim human-reviewed false-merge labels "
            "when using LLM subagent adjudication",
            report["blockers"],
        )

    def test_llm_route_cannot_keep_human_deployment_approval(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())

        def mutate(payload: dict) -> None:
            payload["deployment_approved_by_human"] = True

        rewrite_packet_artifact(packet, "deployment_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter deployment must not claim human approval "
            "when using LLM subagent approval",
            report["blockers"],
        )

    def test_llm_route_rejects_human_false_merge_row_claims(self) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())

        def mutate(payload: dict) -> None:
            row = payload["rows"][0]
            row["human_reviewed"] = True
            row["human_reviewer_id"] = "human_reviewer_retained"
            row["row_sha256"] = validator.row_hash(row)

        rewrite_packet_artifact(packet, "human_false_merge_label_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter false-merge row must not claim human review on LLM route",
            report["blockers"],
        )
        self.assertIn(
            "production adapter false-merge row must not retain a human reviewer id on LLM route",
            report["blockers"],
        )

    def test_default_validator_rejects_test_fixture_artifact_paths(self) -> None:
        report = validator.build_report(valid_packet())

        self.assertFalse(report["passed"])
        self.assertIn(
            "deployment_manifest_artifact test or sandbox artifacts are not accepted under "
            "inputs/production_adapter_real",
            report["blockers"],
        )

    def test_artifact_refs_outside_real_root_fail_even_with_matching_hash(self) -> None:
        packet = valid_packet()
        artifact, digest = write_non_real_artifact(
            "deployment_manifest.json",
            {
                "artifact_type": "production_adapter_deployment_manifest_v1",
                "deployment_id": "deploy_prod_adapter_001",
            },
        )
        packet["deployment_manifest_artifact"] = artifact
        packet["deployment_manifest_artifact_sha256"] = digest
        packet["adapter_artifacts"][0]["artifact"] = "results/production_adapter_component.json"
        packet["adapter_artifacts"][0]["artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "deployment_manifest_artifact path must be under inputs/production_adapter_real",
            report["blockers"],
        )
        self.assertIn(
            "production adapter component artifact path must be under "
            "inputs/production_adapter_real",
            report["blockers"],
        )

    def test_synthetic_or_unapproved_deployment_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["non_synthetic_deployment"] = False
            payload["synthetic_or_demo"] = True
            payload["deployment_approved_by_human"] = False

        rewrite_packet_artifact(packet, "deployment_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter deployment manifest is not non-synthetic", report["blockers"]
        )
        self.assertIn(
            "production adapter deployment manifest is synthetic or demo", report["blockers"]
        )
        self.assertIn("production adapter deployment is not human approved", report["blockers"])

    def test_missing_required_component_fails(self) -> None:
        packet = valid_packet()
        packet["adapter_artifacts"] = [
            ref
            for ref in packet["adapter_artifacts"]
            if ref["component_id"] != "splink_candidate_adapter"
        ]

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter component artifacts missing components: splink_candidate_adapter",
            report["blockers"],
        )

    def test_manifest_adapter_stack_digest_must_bind_component_artifacts(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["adapter_stack_sha256"] = f"{999:064x}"

        rewrite_packet_artifact(packet, "deployment_manifest_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter manifest adapter stack digest mismatch", report["blockers"]
        )

    def test_component_with_canonical_write_or_raw_path_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["canonical_write_enabled"] = True
            payload["raw_path_exposed"] = True
            payload["config_sha256"] = "/mnt/nas/config.json"

        rewrite_adapter_artifact(packet, 0, mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("postgres_metadata_store enables canonical writes", report["blockers"])
        self.assertIn("postgres_metadata_store exposes raw path", report["blockers"])
        self.assertIn(
            "production adapter component artifact contains raw/internal value: config_sha256",
            report["blockers"],
        )

    def test_missing_human_false_merge_label_for_adapter_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"] = [
                row
                for row in payload["rows"]
                if row["adapter_component_id"] != "splink_candidate_adapter"
            ]

        rewrite_packet_artifact(packet, "human_false_merge_label_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter false-merge labels missing adapters: splink_candidate_adapter",
            report["blockers"],
        )

    def test_agent_generated_false_merge_labels_fail(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["reviewer_type"] = "agent"
            payload["synthetic_or_agent_generated"] = True
            payload["rows"][0]["reviewer_type"] = "agent"
            payload["rows"][0]["human_reviewed"] = False
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "human_false_merge_label_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("production adapter false-merge reviewer is not human", report["blockers"])
        self.assertIn(
            "production adapter false-merge labels are synthetic or agent-generated",
            report["blockers"],
        )
        self.assertIn(
            "production adapter false-merge row is not human reviewed", report["blockers"]
        )

    def test_permission_probe_leaks_or_writes_fail(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["raw_asset_access_denied"] = False
            payload["private_leak_count"] = 1
            payload["canonical_write_count"] = 1

        rewrite_packet_artifact(packet, "permission_probe_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter permission probe failed or missing: raw_asset_access_denied",
            report["blockers"],
        )
        self.assertIn(
            "production adapter permission probe positive leak/write count: private_leak_count",
            report["blockers"],
        )
        self.assertIn(
            "production adapter permission probe positive leak/write count: canonical_write_count",
            report["blockers"],
        )

    def test_audit_sequence_or_deny_guard_failure_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"] = [
                row for row in payload["rows"] if row["action"] != "raw_asset_read_guard_rejected"
            ]
            for row in payload["rows"]:
                if row["action"] == "canonical_merge_guard_rejected":
                    row["decision"] = "allow"
                    row["row_sha256"] = validator.row_hash(row)

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("production adapter audit control sequence mismatch", report["blockers"])
        self.assertIn(
            "canonical_merge_guard_rejected is not an explicit deny guard", report["blockers"]
        )

    def test_audit_row_missing_request_id_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["request_id"] = None
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("production adapter audit row request_id missing", report["blockers"])

    def test_audit_row_policy_mismatch_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["policy_id"] = "different_policy"
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("production adapter audit row policy mismatch", report["blockers"])

    def test_audit_rows_must_bind_one_resource_ref(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["resource_ref"] = "formowl://graph-view/other-resource"
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter audit rows do not bind one resource ref", report["blockers"]
        )

    def test_audit_row_rejects_database_internal_uri_value(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["resource_ref"] = "postgres://db.internal/formowl"
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter audit row contains raw/internal value: resource_ref",
            report["blockers"],
        )

    def test_audit_row_rejects_driver_qualified_database_uri_value(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["rows"][0]["resource_ref"] = "postgresql+psycopg2://db.internal/formowl"
            payload["rows"][0]["row_sha256"] = validator.row_hash(payload["rows"][0])

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter audit row contains raw/internal value: resource_ref",
            report["blockers"],
        )

    def test_revoked_grant_audit_row_must_bind_revoked_state(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            row = next(
                row for row in payload["rows"] if row["action"] == "revoked_grant_blocks_content"
            )
            row["grant_state"] = "active"
            row["row_sha256"] = validator.row_hash(row)

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter revoked grant audit row does not bind revoked state",
            report["blockers"],
        )

    def test_positive_audit_lifecycle_actions_must_allow(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            row = next(row for row in payload["rows"] if row["action"] == "deploy_completed")
            row["decision"] = "deny"
            row["row_sha256"] = validator.row_hash(row)

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter audit row decision mismatch: deploy_completed", report["blockers"]
        )

    def test_audit_row_sequence_must_match_required_order(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            row = next(row for row in payload["rows"] if row["action"] == "migration_applied")
            row["sequence"] = 99
            row["row_sha256"] = validator.row_hash(row)

        rewrite_packet_artifact(packet, "audit_trail_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter audit row sequence mismatch: migration_applied", report["blockers"]
        )

    def test_rollback_smoke_missing_verification_fails(self) -> None:
        packet = valid_packet()

        def mutate(payload: dict) -> None:
            payload["partial_failure_rollback_verified"] = False
            payload["audit_append_only_verified"] = False

        rewrite_packet_artifact(packet, "rollback_smoke_artifact", mutate)

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter rollback smoke missing verification: partial_failure_rollback_verified",
            report["blockers"],
        )
        self.assertIn(
            "production adapter rollback smoke missing verification: audit_append_only_verified",
            report["blockers"],
        )

    def test_packet_overclaim_or_lost_tmp_fails(self) -> None:
        packet = valid_packet()
        packet["recovered_after_tmp_loss"] = "true"
        packet["claim_boundary"]["supports_full_product_production_ready_claim"] = "true"

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "production adapter packet cannot rely on lost /tmp artifacts", report["blockers"]
        )
        self.assertIn(
            "production adapter packet overclaims unsupported claim: supports_full_product_production_ready_claim",
            report["blockers"],
        )

    def test_public_reproducible_manifest_can_bind_llm_production_adapter_packet(
        self,
    ) -> None:
        packet = convert_to_llm_subagent_route(valid_packet())
        component_hashes = {
            ref["component_id"]: ref["artifact_sha256"] for ref in packet["adapter_artifacts"]
        }
        add_public_evidence(
            packet,
            "production_adapter_paths",
            validator._public_evidence_hashes(packet, component_hashes),
        )

        report = build_report_for_test(packet)

        self.assertTrue(report["passed"])
        self.assertEqual(report["metrics"]["evidence_source_mode"], public_evidence.PUBLIC_MODE)
        self.assertTrue(report["claim_boundary"][public_evidence.CLAIM_FIELD])


if __name__ == "__main__":
    unittest.main()
