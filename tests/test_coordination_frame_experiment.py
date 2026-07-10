from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import _paths  # noqa: F401
from formowl_graph import coordination_frames as coordination_frame_module

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = (
    REPO_ROOT
    / "experiments"
    / "kg_ontology_v2_coordination"
    / "run_coordination_frame_experiment.py"
)


class CoordinationFrameExperimentTests(unittest.TestCase):
    def test_experiment_compares_current_and_v2_answerability(self) -> None:
        report = _runner().run_experiment()
        arms = report["arms"]

        self.assertEqual(report["experiment_id"], "kg_ontology_v2_coordination_frame_experiment_v1")
        self.assertEqual(report["observation_count"], 4)
        self.assertEqual(report["domain_pack_count"], 5)
        self.assertGreater(
            arms["coordination_frame_v2"]["competency_answerability_score"],
            arms["current_atom_path"]["competency_answerability_score"],
        )
        self.assertGreater(
            arms["coordination_frame_v2"]["slot_recall"],
            arms["current_atom_path"]["slot_recall"],
        )
        self.assertGreater(
            arms["coordination_frame_v2"]["competency_answerability_score"],
            arms["no_ontology_metadata_only"]["competency_answerability_score"],
        )
        self.assertEqual(arms["coordination_frame_v2"]["competency_answerability_score"], 1.0)
        self.assertEqual(arms["coordination_frame_v2"]["slot_recall"], 1.0)
        self.assertEqual(arms["coordination_frame_v2"]["slot_value_recall"], 1.0)
        self.assertEqual(arms["current_atom_path"]["slot_value_recall"], 0.0)
        self.assertGreater(arms["current_atom_path"]["candidate_atom_count"], 0)

    def test_experiment_report_preserves_candidate_only_claim_boundary(self) -> None:
        report = _runner().run_experiment()

        self.assertEqual(
            report["fixture_sources"]["source_kind"], "synthetic_email_cross_domain_fixture"
        )
        self.assertFalse(report["fixture_sources"]["raw_pst_content_used"])
        self.assertTrue(report["claim_boundary"]["candidate_only"])
        self.assertFalse(report["claim_boundary"]["canonical_graph_write_allowed"])
        self.assertFalse(report["claim_boundary"]["canonical_type_write_allowed"])
        self.assertFalse(report["claim_boundary"]["raw_asset_access_granted"])
        self.assertEqual(report["comparison"]["unauthorized_slot_leaks"], 0)
        self.assertEqual(
            report["type_gate_noise_ablation"]["claim_boundary"],
            "synthetic scaffold only; not real email regression evidence",
        )
        self.assertFalse(
            report["effectiveness_regression"]["claim_boundary"]["raw_pst_content_used"]
        )
        self.assertFalse(
            report["effectiveness_regression"]["claim_boundary"]["production_parser_claim"]
        )
        self.assertTrue(all(report["acceptance_checks"].values()))

    def test_external_regression_input_path_is_redacted_from_report(self) -> None:
        default_regression = RUNNER_PATH.parent / "fixtures" / "regression_redacted_cases.json"
        with tempfile.TemporaryDirectory() as temp_dir:
            regression_path = Path(temp_dir) / "external_regression_pack.json"
            regression_path.write_text(default_regression.read_text(encoding="utf-8"))

            report = _runner().run_experiment(regression_path=regression_path)

        fixture_sources = report["fixture_sources"]
        serialized_sources = json.dumps(fixture_sources, sort_keys=True)
        self.assertEqual(fixture_sources["regression"], "external_input_redacted")
        self.assertNotIn(temp_dir, serialized_sources)
        self.assertNotIn("external_regression_pack", serialized_sources)

    def test_v2_statuses_are_answered_for_issue_competency_questions(self) -> None:
        report = _runner().run_experiment()
        statuses = report["arms"]["coordination_frame_v2"]["competency_statuses"]

        self.assertGreaterEqual(len(statuses), 10)
        self.assertEqual({item["status"] for item in statuses}, {"answered"})
        question_ids = {item["question_id"] for item in statuses}
        self.assertIn("cq1_who_requested_what", question_ids)
        self.assertIn("cq2_who_committed", question_ids)
        self.assertIn("cq3_what_was_decided", question_ids)
        self.assertIn("cq4_what_is_blocked", question_ids)
        self.assertIn("cq5_deadline", question_ids)
        self.assertIn("cq6_status_change", question_ids)
        self.assertIn("cq7_evidence", question_ids)
        self.assertIn("cq8_domain", question_ids)
        self.assertIn("cq9_obligation_or_mention", question_ids)
        self.assertIn("cq10_follow_up", question_ids)

    def test_evaluator_scores_frames_only_within_each_gold_case(self) -> None:
        report = coordination_frame_module._evaluate_arm(
            gold_cases=[
                {
                    "case_id": "case_a",
                    "observation_ids": ["obs_case_a"],
                    "required_frame_types": ["Request"],
                    "required_slots": {"Request": ["actor"]},
                    "competency_questions": [
                        {
                            "question_id": "cq_request",
                            "frame_type": "Request",
                            "required_slots": ["actor"],
                        }
                    ],
                },
                {
                    "case_id": "case_b",
                    "observation_ids": ["obs_case_b"],
                    "required_frame_types": ["Request"],
                    "required_slots": {"Request": ["actor"]},
                    "competency_questions": [
                        {
                            "question_id": "cq_request",
                            "frame_type": "Request",
                            "required_slots": ["actor"],
                        }
                    ],
                },
            ],
            frames=[_frame("Request", "obs_case_b", {"actor": "Operations"})],
            candidate_atoms=[],
            warnings=[],
        )

        statuses = {
            (item["case_id"], item["question_id"]): item["status"]
            for item in report["competency_statuses"]
        }
        self.assertEqual(statuses[("case_a", "cq_request")], "not_answered")
        self.assertEqual(statuses[("case_b", "cq_request")], "answered")
        self.assertEqual(report["frame_type_recall"], 0.5)
        self.assertEqual(report["slot_recall"], 0.5)

    def test_required_evidence_question_requires_complete_case_evidence(self) -> None:
        gold_cases = [
            {
                "case_id": "case_a",
                "observation_ids": ["obs_case_a"],
                "required_frame_types": [],
                "required_slots": {},
                "competency_questions": [
                    {
                        "question_id": "cq7_evidence",
                        "frame_type": "Decision",
                        "required_slots": [],
                        "required_evidence": True,
                    }
                ],
            }
        ]

        missing_evidence_report = coordination_frame_module._evaluate_arm(
            gold_cases=gold_cases,
            frames=[
                {
                    **_frame("Decision", "obs_case_a", {"decision": "ship in phases"}),
                    "evidence_spans": [
                        {
                            "span_id": "span_obs_case_a_1",
                            "source_observation_id": "obs_case_a",
                        }
                    ],
                }
            ],
            candidate_atoms=[],
            warnings=[],
        )
        wrong_case_evidence_report = coordination_frame_module._evaluate_arm(
            gold_cases=gold_cases,
            frames=[
                {
                    **_frame("Decision", "obs_case_a", {"decision": "ship in phases"}),
                    "evidence_spans": [
                        {
                            "span_id": "span_obs_case_b_1",
                            "source_observation_id": "obs_case_b",
                            "locator": {"line": 1},
                            "text_hash": "sha256:case-b",
                        }
                    ],
                }
            ],
            candidate_atoms=[],
            warnings=[],
        )

        self.assertEqual(
            missing_evidence_report["competency_statuses"][0]["status"],
            "partially_answered",
        )
        self.assertEqual(
            wrong_case_evidence_report["competency_statuses"][0]["status"],
            "partially_answered",
        )

    def test_slot_value_recall_catches_wrong_slot_values(self) -> None:
        gold_cases = [
            {
                "case_id": "case_a",
                "observation_ids": ["obs_case_a"],
                "required_frame_types": ["Deadline"],
                "required_slots": {"Deadline": ["target", "deadline"]},
                "expected_slot_values": {
                    "Deadline": {
                        "target": "Quote v2",
                        "deadline": "2026-07-20",
                    }
                },
                "competency_questions": [
                    {
                        "question_id": "cq_deadline",
                        "frame_type": "Deadline",
                        "required_slots": ["target", "deadline"],
                    }
                ],
            }
        ]

        report = coordination_frame_module._evaluate_arm(
            gold_cases=gold_cases,
            frames=[
                _frame(
                    "Deadline",
                    "obs_case_a",
                    {"target": "Quote v2", "deadline": "2026-08-01"},
                )
            ],
            candidate_atoms=[],
            warnings=[],
        )

        self.assertEqual(report["slot_recall"], 1.0)
        self.assertEqual(report["slot_value_recall"], 0.5)
        self.assertEqual(report["competency_statuses"][0]["status"], "answered")

    def test_type_gate_noise_ablation_keeps_soft_gate_candidate_only(self) -> None:
        ablation = _runner().run_experiment()["type_gate_noise_ablation"]

        self.assertEqual(ablation["hard_gate_false_reject_count"], 2)
        self.assertEqual(ablation["soft_gate_false_reject_count"], 0)
        self.assertEqual(ablation["soft_gate_high_confidence_negative_reject_count"], 1)
        noisy_cases = {
            item["case_id"]: item
            for item in ablation["cases"]
            if item["case_id"].endswith("_noisy")
        }
        for item in noisy_cases.values():
            self.assertTrue(item["hard_gate_rejects"])
            self.assertFalse(item["soft_gate_hard_rejects"])
            self.assertEqual(
                item["soft_gate_reason"],
                "low_confidence_core_supertype_mismatch_soft_prior",
            )

    def test_redacted_effectiveness_reproduces_hard_ontology_regression(self) -> None:
        report = _runner().run_experiment()["effectiveness_regression"]
        arms = report["arms"]
        summary = report["summary"]

        self.assertEqual(
            set(arms),
            {
                "kg_without_ontology",
                "kg_hard_ontology",
                "kg_soft_ontology_gate",
                "coordination_frame_v2_redacted",
                "hybrid_soft_gate_v2_frame",
            },
        )
        self.assertEqual(report["source_kind"], "pst_redacted_replay_fixture")
        self.assertEqual(report["case_count"], 6)
        self.assertEqual(report["positive_case_count"], 5)
        self.assertTrue(summary["hard_ontology_regression_reproduced"])
        self.assertEqual(summary["hard_ontology_delta_vs_kg_without_ontology"], -0.5)
        self.assertEqual(arms["kg_without_ontology"]["exact_match_rate"], 0.666667)
        self.assertEqual(arms["kg_hard_ontology"]["exact_match_rate"], 0.166667)
        self.assertEqual(arms["kg_hard_ontology"]["hard_gate_false_reject_count"], 2)
        self.assertEqual(arms["kg_hard_ontology"]["alignment_suppressed_count"], 1)
        self.assertEqual(arms["kg_hard_ontology"]["structure_mislead_count"], 1)

    def test_redacted_effectiveness_shows_soft_gate_and_v2_effect(self) -> None:
        report = _runner().run_experiment()["effectiveness_regression"]
        arms = report["arms"]
        summary = report["summary"]

        self.assertEqual(arms["kg_soft_ontology_gate"]["exact_match_rate"], 0.666667)
        self.assertEqual(arms["kg_soft_ontology_gate"]["hard_gate_false_reject_count"], 0)
        self.assertEqual(summary["soft_gate_delta_vs_hard_ontology"], 0.5)
        self.assertTrue(summary["soft_gate_reduces_hard_false_rejects"])
        self.assertEqual(arms["coordination_frame_v2_redacted"]["exact_match_rate"], 1.0)
        self.assertEqual(arms["hybrid_soft_gate_v2_frame"]["exact_match_rate"], 1.0)
        self.assertEqual(summary["v2_delta_vs_hard_ontology"], 0.833333)
        self.assertEqual(summary["hybrid_delta_vs_kg_without_ontology"], 0.333333)
        self.assertTrue(summary["v2_effective_on_redacted_replay"])
        self.assertTrue(summary["hybrid_improves_over_hard_and_kg_without_ontology"])

    def test_redacted_effectiveness_scores_false_positive_guard(self) -> None:
        report = _runner().run_experiment()["effectiveness_regression"]

        self.assertEqual(report["arms"]["kg_without_ontology"]["false_positive_count"], 1)
        for arm in (
            "kg_hard_ontology",
            "kg_soft_ontology_gate",
            "coordination_frame_v2_redacted",
            "hybrid_soft_gate_v2_frame",
        ):
            self.assertEqual(report["arms"][arm]["false_positive_count"], 0)
        hard_negative = next(
            item
            for item in report["arms"]["kg_hard_ontology"]["case_results"]
            if item["case_id"] == "redacted_high_confidence_negative"
        )
        self.assertEqual(hard_negative["status"], "correct_no_answer")
        self.assertEqual(hard_negative["missing_reason"], "hard_gate_reject")

    def test_ablation_versions_keep_original_fixture_and_new_100_case_challenge(
        self,
    ) -> None:
        versions = _runner().run_experiment()["ablation_versions"]

        self.assertEqual(
            set(versions),
            {
                "original_synthetic_marker_fixture",
                "redacted_hard_challenge_100",
                "redacted_stress_benchmark_10000",
            },
        )
        original = versions["original_synthetic_marker_fixture"]
        self.assertEqual(original["case_count"], 4)
        self.assertEqual(
            original["claim_boundary"],
            "round-trip contract verification; not production parser evidence",
        )
        self.assertEqual(
            original["arms"]["coordination_frame_v2"]["competency_answerability_score"],
            1.0,
        )
        self.assertEqual(
            original["arms"]["current_atom_path"]["competency_answerability_score"],
            0.09375,
        )

        challenge = versions["redacted_hard_challenge_100"]
        self.assertEqual(challenge["case_count"], 100)
        self.assertEqual(challenge["split_counts"], {"dev": 30, "holdout": 70})
        self.assertEqual(
            challenge["failure_bucket_counts"],
            {
                "access_or_redaction_boundary": 5,
                "alignment_suppressed": 15,
                "cross_thread_dependency": 10,
                "false_positive_guard": 10,
                "followup_or_fallback_missing": 10,
                "frame_type_confusion": 15,
                "gate_false_reject": 20,
                "structure_misleads": 15,
            },
        )

        stress = versions["redacted_stress_benchmark_10000"]
        self.assertEqual(stress["case_count"], 10000)
        self.assertEqual(stress["split_counts"], {"dev": 1000, "holdout": 9000})
        self.assertEqual(stress["generation"]["scale_factor"], 100)
        self.assertEqual(
            stress["generation"]["seed_dataset_id"],
            "redacted_hard_challenge_100_v1",
        )

    def test_redacted_hard_challenge_100_ablation_metrics(self) -> None:
        challenge = _runner().run_experiment()["hard_challenge_100"]
        arms = challenge["arms"]
        summary = challenge["summary"]

        self.assertEqual(challenge["dataset_id"], "redacted_hard_challenge_100_v1")
        self.assertEqual(challenge["case_count"], 100)
        self.assertEqual(challenge["positive_case_count"], 85)
        self.assertTrue(summary["hard_ontology_regression_reproduced"])
        self.assertEqual(summary["hard_ontology_delta_vs_kg_without_ontology"], -0.24)
        self.assertEqual(summary["soft_gate_delta_vs_hard_ontology"], 0.52)
        self.assertEqual(summary["v2_delta_vs_hard_ontology"], 0.6)
        self.assertEqual(summary["hybrid_delta_vs_kg_without_ontology"], 0.44)
        self.assertEqual(summary["best_arm_by_exact_match"], "hybrid_soft_gate_v2_frame")

        self.assertEqual(arms["kg_without_ontology"]["exact_match_rate"], 0.46)
        self.assertEqual(arms["kg_without_ontology"]["false_positive_count"], 11)
        self.assertEqual(arms["kg_hard_ontology"]["exact_match_rate"], 0.22)
        self.assertEqual(arms["kg_hard_ontology"]["hard_gate_false_reject_count"], 30)
        self.assertEqual(arms["kg_soft_ontology_gate"]["exact_match_rate"], 0.74)
        self.assertEqual(arms["kg_soft_ontology_gate"]["hard_gate_false_reject_count"], 0)
        self.assertEqual(arms["coordination_frame_v2_redacted"]["exact_match_rate"], 0.82)
        self.assertEqual(arms["hybrid_soft_gate_v2_frame"]["exact_match_rate"], 0.9)
        self.assertEqual(arms["hybrid_soft_gate_v2_frame"]["slot_value_f1"], 0.981133)

    def test_redacted_stress_benchmark_10000_distribution_and_metrics(self) -> None:
        stress = _runner().run_experiment()["redacted_stress_benchmark_10000"]
        arms = stress["arms"]
        summary = stress["summary"]

        self.assertEqual(stress["dataset_id"], "redacted_stress_benchmark_10000_v1")
        self.assertEqual(stress["source_kind"], "deterministic_redacted_stress_benchmark")
        self.assertFalse(stress["case_results_included"])
        self.assertEqual(stress["case_count"], 10000)
        self.assertEqual(stress["positive_case_count"], 8500)
        self.assertEqual(stress["split_counts"], {"dev": 1000, "holdout": 9000})
        self.assertEqual(
            stress["failure_bucket_counts"],
            {
                "access_or_redaction_boundary": 500,
                "alignment_suppressed": 1500,
                "cross_thread_dependency": 1000,
                "false_positive_guard": 1000,
                "followup_or_fallback_missing": 1000,
                "frame_type_confusion": 1500,
                "gate_false_reject": 2000,
                "structure_misleads": 1500,
            },
        )
        self.assertTrue(
            stress["claim_boundary"]["generated_from_redacted_templates"],
        )
        self.assertFalse(stress["claim_boundary"]["held_out_parser_output_claim"])
        self.assertFalse(stress["claim_boundary"]["production_parser_claim"])
        self.assertFalse(stress["claim_boundary"]["raw_pst_content_used"])
        self.assertIn(
            "not independent PST holdout", stress["generation"]["template_leakage_boundary"]
        )
        self.assertNotIn("case_results", arms["hybrid_soft_gate_v2_frame"])

        self.assertTrue(summary["hard_ontology_regression_reproduced"])
        self.assertEqual(summary["hard_ontology_delta_vs_kg_without_ontology"], -0.24)
        self.assertEqual(summary["soft_gate_delta_vs_hard_ontology"], 0.52)
        self.assertEqual(summary["v2_delta_vs_hard_ontology"], 0.6)
        self.assertEqual(summary["hybrid_delta_vs_kg_without_ontology"], 0.44)
        self.assertEqual(summary["best_arm_by_exact_match"], "hybrid_soft_gate_v2_frame")

        self.assertEqual(arms["kg_without_ontology"]["exact_match_rate"], 0.46)
        self.assertEqual(arms["kg_without_ontology"]["false_positive_count"], 1100)
        self.assertEqual(arms["kg_hard_ontology"]["exact_match_rate"], 0.22)
        self.assertEqual(arms["kg_hard_ontology"]["hard_gate_false_reject_count"], 3000)
        self.assertEqual(arms["kg_soft_ontology_gate"]["exact_match_rate"], 0.74)
        self.assertEqual(arms["kg_soft_ontology_gate"]["hard_gate_false_reject_count"], 0)
        self.assertEqual(arms["coordination_frame_v2_redacted"]["exact_match_rate"], 0.82)
        self.assertEqual(arms["coordination_frame_v2_redacted"]["false_positive_count"], 100)
        self.assertEqual(arms["hybrid_soft_gate_v2_frame"]["exact_match_rate"], 0.9)
        self.assertEqual(arms["hybrid_soft_gate_v2_frame"]["slot_value_f1"], 0.981133)
        self.assertEqual(arms["hybrid_soft_gate_v2_frame"]["false_positive_count"], 100)

    def test_redacted_stress_benchmark_rejects_malformed_seed_challenge(self) -> None:
        default_challenge = RUNNER_PATH.parent / "fixtures" / "challenge_redacted_100_cases.json"
        malformed = json.loads(default_challenge.read_text(encoding="utf-8"))
        malformed["cases"] = malformed["cases"][:-1]

        with tempfile.TemporaryDirectory() as temp_dir:
            challenge_path = Path(temp_dir) / "malformed_challenge.json"
            challenge_path.write_text(json.dumps(malformed), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "exactly 100 cases"):
                _runner().run_experiment(challenge_path=challenge_path)


def _runner():
    spec = importlib.util.spec_from_file_location("coordination_frame_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load coordination frame experiment runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frame(frame_type: str, observation_id: str, slots: dict[str, str]) -> dict[str, object]:
    return {
        "frame_type": frame_type,
        "source_observation_ids": [observation_id],
        "slots": slots,
        "evidence_spans": [
            {
                "span_id": f"span_{observation_id}_1",
                "source_observation_id": observation_id,
                "locator": {"line": 1},
                "text_hash": f"sha256:{observation_id}",
            }
        ],
        "domain_hints": ["fixture"],
        "access_boundary": {
            "boundary_type": "source_observation_scope",
            "raw_access_required": False,
        },
    }


if __name__ == "__main__":
    unittest.main()
