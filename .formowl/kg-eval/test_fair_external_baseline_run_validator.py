#!/usr/bin/env python3
"""Tests for fair external baseline run evidence validation."""

from __future__ import annotations

from copy import deepcopy
import json
import shutil
import unittest

import fair_external_baseline_run_validator as validator


BASE = validator.REAL_ARTIFACT_ROOT_PATH / "validator_fixture"
SHARED_HASHES = {
    "corpus_export_sha256": "1234567890abcdef" * 4,
    "prompt_set_sha256": "234567890abcdef1" * 4,
    "evaluation_question_set_sha256": "34567890abcdef12" * 4,
    "access_policy_sha256": "4567890abcdef123" * 4,
    "completion_model_budget_sha256": "567890abcdef1234" * 4,
    "embedding_model_budget_sha256": "67890abcdef12345" * 4,
    "ontology_mapping_sha256": "7890abcdef123456" * 4,
}
RUN_MANIFEST_SHA256 = "90abcdef12345678" * 4


def write_artifact(relative_name: str, payload: object) -> tuple[str, str]:
    path = BASE / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return (
        f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/{relative_name}",
        validator.sha256_file(path) or "",
    )


def write_raw(relative_name: str, content: str) -> tuple[str, str]:
    path = BASE / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return (
        f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/{relative_name}",
        validator.sha256_file(path) or "",
    )


def write_non_real_artifact(relative_name: str, payload: object) -> tuple[str, str]:
    path = validator.INPUTS / "test_fair_baseline_rejected" / relative_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return f"inputs/test_fair_baseline_rejected/{relative_name}", validator.sha256_file(path) or ""


def remove_path(path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)


def build_report_for_test(packet: dict) -> dict:
    return validator.build_report(packet, allow_test_artifacts=True)


def rewrite_run_artifact(
    packet: dict,
    *,
    baseline_id: str,
    artifact_field: str,
    payload: object,
) -> None:
    run = next(row for row in packet["baseline_runs"] if row["baseline_id"] == baseline_id)
    path = validator.safe_relative_artifact_path(
        run[artifact_field],
        allow_test_artifacts=True,
    )
    assert path is not None
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run[f"{artifact_field}_sha256"] = validator.sha256_file(path) or ""


def valid_artifact_payload(baseline_id: str, artifact_field: str, run: dict) -> dict:
    payload = {
        "artifact_type": validator.EXPECTED_RUN_ARTIFACT_TYPES[artifact_field],
        "baseline_id": baseline_id,
        "source_lock_sha256": validator.literature.required_baseline_source_lock_sha256(),
        "source_ids": list(validator.REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]),
        "package_source_url": validator.REQUIRED_BASELINE_URLS[baseline_id],
        "package_version": run["package_version"],
        "real_package_execution": True,
        "mock_or_dry_run": False,
        "synthetic_corpus": False,
        "uses_mocked_llm_or_retrieval": False,
        "run_manifest_sha256": RUN_MANIFEST_SHA256,
    }
    if artifact_field == "package_lock_artifact":
        payload.update(
            {
                "package_lock_sha256": "abcdef1234567890" * 4,
                "package_resolved": True,
            }
        )
    elif artifact_field == "config_artifact":
        payload.update(SHARED_HASHES)
    elif artifact_field == "index_build_log_artifact":
        payload.update(
            {
                "index_build_completed": True,
                "indexed_document_count": 5,
            }
        )
    elif artifact_field == "query_run_log_artifact":
        payload.update(
            {
                "query_run_completed": True,
                "evaluation_question_set_sha256": run["evaluation_question_set_sha256"],
                "query_count": 12,
            }
        )
    elif artifact_field == "answer_output_artifact":
        payload.update(
            {
                "generated_by_real_package": True,
                "evaluation_question_set_sha256": run["evaluation_question_set_sha256"],
                "answer_count": 12,
            }
        )
    elif artifact_field == "graph_output_artifact":
        payload.update(
            {
                "generated_by_real_package": True,
                "entity_count": 20,
                "relation_count": 16,
            }
        )
    elif artifact_field == "permission_probe_artifact":
        payload.update(
            {
                "revoked_grant_content_denied": True,
                "private_content_not_returned": True,
                "raw_asset_access_denied": True,
                "entity_match_does_not_grant_access": True,
                "private_content_leak_count": 0,
                "raw_asset_access_count": 0,
            }
        )
    return payload


def valid_packet() -> dict:
    baseline_runs = []
    for baseline_id in validator.REQUIRED_BASELINES:
        run = {
            "baseline_id": baseline_id,
            "package_source_url": validator.REQUIRED_BASELINE_URLS[baseline_id],
            "source_ids": list(validator.REQUIRED_SOURCE_IDS_BY_BASELINE[baseline_id]),
            "package_version": f"{baseline_id}-release-2026-06",
            "real_package_execution": True,
            "mock_or_dry_run": False,
            "synthetic_corpus": False,
            **SHARED_HASHES,
        }
        for artifact_field in validator.RUN_ARTIFACT_FIELDS:
            artifact, digest = write_artifact(
                f"{baseline_id}/{artifact_field}.json",
                valid_artifact_payload(baseline_id, artifact_field, run),
            )
            run[artifact_field] = artifact
            run[f"{artifact_field}_sha256"] = digest
        baseline_runs.append(run)

    return {
        "artifact_id": "fair_external_baseline_run_packet_v1",
        "evidence_kind": "non_synthetic_external_baseline_run",
        "recovered_after_tmp_loss": False,
        "run_environment": {
            "non_synthetic_benchmark_context": True,
            "uses_real_external_packages": True,
            "uses_mocked_llm_or_retrieval": False,
            "container_image_digest_sha256": "890abcdef1234567" * 4,
            "run_manifest_sha256": RUN_MANIFEST_SHA256,
        },
        "source_lock_sha256": validator.literature.required_baseline_source_lock_sha256(),
        "baseline_runs": baseline_runs,
        "human_answer_adjudication": {
            "artifact_id": "human_answer_adjudication_results_v1",
            "completed": True,
            "synthetic_or_agent_generated": False,
            "question_set_sha256": SHARED_HASHES["evaluation_question_set_sha256"],
            "reviewers": [
                {
                    "reviewer_id": "human_reviewer_a",
                    "reviewer_type": "human",
                    "independent_first_pass": True,
                    "sealed_submission_sha256": "abcdef1234567890" * 4,
                },
                {
                    "reviewer_id": "human_reviewer_b",
                    "reviewer_type": "human",
                    "independent_first_pass": True,
                    "sealed_submission_sha256": "bcdef1234567890a" * 4,
                },
            ],
            "adjudicator_id": "human_adjudicator_c",
            "final_adjudication_sha256": "cdef1234567890ab" * 4,
            "custody_receipt_sha256": "def1234567890abc" * 4,
            "per_baseline_rows": [
                {
                    "baseline_id": run["baseline_id"],
                    "question_count": 12,
                    "answer_output_artifact_sha256": run["answer_output_artifact_sha256"],
                }
                for run in baseline_runs
            ],
        },
        "graph_quality_validation": {
            "completed": True,
            "human_reviewed": True,
            "per_baseline_rows": [
                {
                    "baseline_id": run["baseline_id"],
                    "graph_output_artifact_sha256": run["graph_output_artifact_sha256"],
                    "reviewed_entity_count": 20,
                    "reviewed_relation_count": 16,
                }
                for run in baseline_runs
            ],
        },
        "permission_probes": [
            {
                "baseline_id": run["baseline_id"],
                "permission_probe_artifact_sha256": run["permission_probe_artifact_sha256"],
                "revoked_grant_content_denied": True,
                "private_content_not_returned": True,
                "raw_asset_access_denied": True,
                "entity_match_does_not_grant_access": True,
                "private_content_leak_count": 0,
                "raw_asset_access_count": 0,
            }
            for run in baseline_runs
        ],
        "claim_boundary": {
            "supports_fair_external_baseline_comparison_claim": True,
            "supports_production_ready_claim": False,
            "supports_top_tier_scientific_validation_claim": False,
            "supports_unreviewed_business_judgment_claim": False,
            "supports_unreviewed_canonical_merge_claim": False,
        },
    }


class FairExternalBaselineRunValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_fair_baseline_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)
        shutil.rmtree(validator.INPUTS / "test_fair_baseline_rejected", ignore_errors=True)
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "templates")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release_alias")
        remove_path(validator.REAL_ARTIFACT_ROOT_PATH / "release.template.json")

    def test_missing_input_packet_fails_broad_gate(self) -> None:
        report = build_report_for_test({})

        self.assertFalse(report["passed"])
        self.assertIn("fair external baseline run packet missing", report["blockers"])
        self.assertFalse(
            report["claim_boundary"]["supports_fair_external_baseline_comparison_claim"]
        )

    def test_default_validator_rejects_templates_under_real_root(self) -> None:
        packet = valid_packet()
        run = packet["baseline_runs"][0]
        for field, relative_name in (
            ("package_lock_artifact", "templates/package_lock.json"),
            ("config_artifact", "release.template.json"),
        ):
            source = validator.safe_relative_artifact_path(
                run[field],
                allow_test_artifacts=True,
            )
            assert source is not None
            path = validator.REAL_ARTIFACT_ROOT_PATH / relative_name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
            run[field] = f"{validator.REAL_ARTIFACT_ROOT}/{relative_name}"
            run[f"{field}_sha256"] = validator.sha256_file(path) or ""

        report = validator.build_report(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            f"{run['baseline_id']} package_lock_artifact template artifacts are not accepted under "
            "inputs/fair_baseline_real",
            report["blockers"],
        )
        self.assertIn(
            f"{run['baseline_id']} config_artifact template artifacts are not accepted under "
            "inputs/fair_baseline_real",
            report["blockers"],
        )

    def test_default_validator_rejects_symlink_alias_to_sandbox_artifacts(self) -> None:
        packet = valid_packet()
        alias = validator.REAL_ARTIFACT_ROOT_PATH / "release_alias"
        alias.symlink_to(BASE, target_is_directory=True)
        original_prefix = f"{validator.REAL_ARTIFACT_ROOT}/validator_fixture/"
        alias_prefix = f"{validator.REAL_ARTIFACT_ROOT}/release_alias/"
        for run in packet["baseline_runs"]:
            for field in validator.RUN_ARTIFACT_FIELDS:
                run[field] = run[field].replace(original_prefix, alias_prefix)

        report = validator.build_report(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            f"{packet['baseline_runs'][0]['baseline_id']} package_lock_artifact artifact symlinks "
            "are not accepted under inputs/fair_baseline_real",
            report["blockers"],
        )

    def test_structurally_complete_packet_passes_validator(self) -> None:
        report = build_report_for_test(valid_packet())

        self.assertTrue(report["passed"])
        self.assertEqual(report["blockers"], [])
        self.assertEqual(report["metrics"]["baseline_run_count"], 3)
        self.assertTrue(report["claim_boundary"]["supports_real_package_execution_claim"])
        self.assertFalse(report["claim_boundary"]["supports_production_ready_claim"])

    def test_default_validator_rejects_test_fixture_artifact_paths(self) -> None:
        report = validator.build_report(valid_packet())

        self.assertFalse(report["passed"])
        self.assertIn(
            "microsoft_graphrag package_lock_artifact "
            "test or sandbox artifacts are not accepted under inputs/fair_baseline_real",
            report["blockers"],
        )

    def test_artifact_refs_outside_real_root_fail_even_with_matching_hash(self) -> None:
        packet = valid_packet()
        microsoft = next(
            row for row in packet["baseline_runs"] if row["baseline_id"] == "microsoft_graphrag"
        )
        lightrag = next(row for row in packet["baseline_runs"] if row["baseline_id"] == "lightrag")
        artifact, digest = write_non_real_artifact(
            "package_lock_artifact.json",
            valid_artifact_payload(
                "microsoft_graphrag",
                "package_lock_artifact",
                microsoft,
            ),
        )
        microsoft["package_lock_artifact"] = artifact
        microsoft["package_lock_artifact_sha256"] = digest
        lightrag["config_artifact"] = "results/fair_baseline_config_artifact.json"
        lightrag["config_artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "microsoft_graphrag package_lock_artifact path must be under "
            "inputs/fair_baseline_real",
            report["blockers"],
        )
        self.assertIn(
            "lightrag config_artifact path must be under inputs/fair_baseline_real",
            report["blockers"],
        )

    def test_missing_required_baseline_run_fails(self) -> None:
        packet = valid_packet()
        packet["baseline_runs"] = [
            run for run in packet["baseline_runs"] if run["baseline_id"] != "hipporag"
        ]

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("fair baseline package runs missing baselines: hipporag", report["blockers"])

    def test_artifact_hash_mismatch_fails(self) -> None:
        packet = valid_packet()
        packet["baseline_runs"][0]["answer_output_artifact_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "microsoft_graphrag answer_output_artifact missing or hash mismatch", report["blockers"]
        )

    def test_run_artifacts_must_have_content_contract_not_only_hashes(self) -> None:
        packet = valid_packet()
        rewrite_run_artifact(
            packet,
            baseline_id="microsoft_graphrag",
            artifact_field="package_lock_artifact",
            payload={"artifact_type": "generic_json_v1"},
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "microsoft_graphrag package_lock_artifact artifact type mismatch",
            report["blockers"],
        )
        self.assertIn(
            "microsoft_graphrag package_lock_artifact baseline binding mismatch",
            report["blockers"],
        )

    def test_run_artifacts_must_be_json_objects(self) -> None:
        packet = valid_packet()
        run = next(row for row in packet["baseline_runs"] if row["baseline_id"] == "lightrag")
        artifact, digest = write_raw("lightrag/index_build_log_artifact.txt", "index completed\n")
        run["index_build_log_artifact"] = artifact
        run["index_build_log_artifact_sha256"] = digest

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "lightrag index_build_log_artifact artifact content is not a JSON object",
            report["blockers"],
        )

    def test_run_artifact_content_must_bind_equalized_config_and_source_lock(self) -> None:
        packet = valid_packet()
        run = next(row for row in packet["baseline_runs"] if row["baseline_id"] == "hipporag")
        payload = valid_artifact_payload("hipporag", "config_artifact", run)
        payload["source_lock_sha256"] = "abcdef1234567890" * 4
        payload["prompt_set_sha256"] = "abcdef1234567890" * 4
        rewrite_run_artifact(
            packet,
            baseline_id="hipporag",
            artifact_field="config_artifact",
            payload=payload,
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("hipporag config_artifact source lock binding mismatch", report["blockers"])
        self.assertIn(
            "hipporag config artifact does not bind equalized field: prompt_set_sha256",
            report["blockers"],
        )

    def test_permission_probe_artifact_content_must_have_zero_leaks(self) -> None:
        packet = valid_packet()
        run = next(row for row in packet["baseline_runs"] if row["baseline_id"] == "lightrag")
        payload = valid_artifact_payload("lightrag", "permission_probe_artifact", run)
        payload["entity_match_does_not_grant_access"] = False
        payload["private_content_leak_count"] = 1
        rewrite_run_artifact(
            packet,
            baseline_id="lightrag",
            artifact_field="permission_probe_artifact",
            payload=payload,
        )

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "lightrag permission probe artifact failed or missing: entity_match_does_not_grant_access",
            report["blockers"],
        )
        self.assertIn(
            "lightrag permission probe artifact leaked private content",
            report["blockers"],
        )

    def test_mock_or_synthetic_run_fails(self) -> None:
        packet = valid_packet()
        packet["run_environment"]["uses_mocked_llm_or_retrieval"] = True
        packet["baseline_runs"][1]["mock_or_dry_run"] = True
        packet["baseline_runs"][1]["synthetic_corpus"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline run environment allows mocked LLM/retrieval", report["blockers"]
        )
        self.assertIn("lightrag run is marked as mock or dry run", report["blockers"])
        self.assertIn("lightrag run used synthetic corpus", report["blockers"])

    def test_runs_must_share_equalized_policy_hashes(self) -> None:
        packet = valid_packet()
        packet["baseline_runs"][2]["prompt_set_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline runs are not equalized for prompt_set_sha256", report["blockers"]
        )

    def test_real_packet_must_bind_to_literature_source_lock(self) -> None:
        packet = valid_packet()
        packet.pop("source_lock_sha256")

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn("fair baseline source lock hash missing or weak", report["blockers"])

        packet = valid_packet()
        packet["source_lock_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline source lock hash does not match literature protocol",
            report["blockers"],
        )

    def test_baseline_runs_must_bind_to_locked_source_ids(self) -> None:
        packet = valid_packet()
        hipporag = next(run for run in packet["baseline_runs"] if run["baseline_id"] == "hipporag")
        hipporag["source_ids"] = ["hipporag_paper", "hipporag_repo"]

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "hipporag source ids do not match locked literature source list",
            report["blockers"],
        )

    def test_human_adjudication_cannot_be_agent_generated(self) -> None:
        packet = valid_packet()
        packet["human_answer_adjudication"]["synthetic_or_agent_generated"] = True
        packet["human_answer_adjudication"]["reviewers"][0]["reviewer_type"] = "agent"

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human answer-quality adjudication is synthetic or agent-generated", report["blockers"]
        )
        self.assertIn("human answer-quality reviewer is not marked human", report["blockers"])

    def test_human_adjudication_question_set_must_match_package_runs(self) -> None:
        packet = valid_packet()
        packet["human_answer_adjudication"]["question_set_sha256"] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "human answer-quality question set is not bound to package evaluation question set",
            report["blockers"],
        )

    def test_human_rows_must_bind_to_answer_outputs(self) -> None:
        packet = valid_packet()
        packet["human_answer_adjudication"]["per_baseline_rows"][0][
            "answer_output_artifact_sha256"
        ] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "microsoft_graphrag human answer-quality row is not bound to package answer output",
            report["blockers"],
        )

    def test_graph_quality_rows_must_bind_to_graph_outputs(self) -> None:
        packet = valid_packet()
        packet["graph_quality_validation"]["per_baseline_rows"][1][
            "graph_output_artifact_sha256"
        ] = "abcdef1234567890" * 4

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "lightrag graph-quality row is not bound to package graph output", report["blockers"]
        )

    def test_permission_probe_leak_fails(self) -> None:
        packet = valid_packet()
        packet["permission_probes"][2]["private_content_not_returned"] = False
        packet["permission_probes"][2]["private_content_leak_count"] = 1

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "hipporag permission probe failed or missing: private_content_not_returned",
            report["blockers"],
        )
        self.assertIn("hipporag permission probe leaked private content", report["blockers"])

    def test_packet_cannot_overclaim_top_tier_or_production(self) -> None:
        packet = valid_packet()
        packet["claim_boundary"]["supports_production_ready_claim"] = True
        packet["claim_boundary"]["supports_top_tier_scientific_validation_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline packet overclaims unsupported claim: supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "fair baseline packet overclaims unsupported claim: supports_top_tier_scientific_validation_claim",
            report["blockers"],
        )

    def test_packet_rejects_string_truthy_or_unknown_claim_boundary_fields(self) -> None:
        packet = valid_packet()
        packet["claim_boundary"]["supports_production_ready_claim"] = "true"
        packet["claim_boundary"]["supports_goal_complete_claim"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline packet overclaims unsupported claim: supports_production_ready_claim",
            report["blockers"],
        )
        self.assertIn(
            "fair baseline packet claim boundary has unsupported fields: supports_goal_complete_claim",
            report["blockers"],
        )

    def test_lost_tmp_recovery_packet_fails(self) -> None:
        packet = deepcopy(valid_packet())
        packet["recovered_after_tmp_loss"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline run packet cannot rely on lost /tmp artifacts", report["blockers"]
        )

    def test_packet_rejects_template_only_extra_fields(self) -> None:
        packet = valid_packet()
        packet["template_only"] = True

        report = build_report_for_test(packet)

        self.assertFalse(report["passed"])
        self.assertIn(
            "fair baseline run packet has unsupported fields: template_only", report["blockers"]
        )


if __name__ == "__main__":
    unittest.main()
