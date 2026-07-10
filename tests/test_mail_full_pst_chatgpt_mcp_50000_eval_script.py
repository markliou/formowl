from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
import unittest

import _paths
from formowl_contract import sha256_json


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "mail_full_pst_chatgpt_mcp_50000_eval.py"
)


def _load_eval_module(module_name: str = "mail_full_pst_chatgpt_mcp_50000_eval"):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ChatGPT MCP 50K evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class MailFullPstChatgptMcp50000EvalScriptTests(unittest.TestCase):
    def test_deterministic_scaled_generation_and_private_outputs(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-chatgpt-mcp-50k-deterministic")
        inputs = _write_synthetic_inputs(module, temp_dir)
        dimensions = module.ExpansionDimensions(
            personas=("manager", "reviewer"),
            urgencies=("routine",),
            answer_formats=("brief",),
            conversation_styles=("single_turn", "follow_up_refinement"),
        )

        first = _run_with_opt_in(
            module,
            inputs=inputs,
            private_dir=temp_dir / "private-first",
            dimensions=dimensions,
        )
        second = _run_with_opt_in(
            module,
            inputs=inputs,
            private_dir=temp_dir / "private-second",
            dimensions=dimensions,
        )

        self.assertTrue(first["validation"]["passed"], first["validation"]["blockers"])
        self.assertEqual(first["safe_outputs"]["base_case_count"], 3)
        self.assertEqual(first["safe_outputs"]["scenario_count_per_base_case"], 4)
        self.assertEqual(first["safe_outputs"]["expanded_case_count"], 12)
        self.assertEqual(first["safe_outputs"]["unique_evidence_case_count"], 3)
        self.assertEqual(first["safe_outputs"]["rendered_scenario_count"], 12)
        self.assertNotIn("public_rows", first["safe_outputs"])
        self.assertLess(
            len(json.dumps(first, sort_keys=True).encode()),
            module.MAX_PUBLIC_REPORT_BYTES,
        )
        self.assertEqual(
            first["safe_outputs"]["private_artifact_manifest_hash"],
            second["safe_outputs"]["private_artifact_manifest_hash"],
        )
        private_manifest = json.loads(
            (temp_dir / "private-first" / module.PRIVATE_MANIFEST_FILENAME).read_text()
        )
        private_rows = json.loads(
            (temp_dir / "private-first" / module.PRIVATE_ROWS_FILENAME).read_text()
        )
        self.assertEqual(private_manifest["expanded_case_count"], 12)
        self.assertEqual(len(private_manifest["cases"]), 12)
        self.assertEqual(len(private_rows["rows"]), 12)
        self.assertIn("private owner query", private_manifest["cases"][0]["user_query"])
        self.assertIn("trajectory", private_manifest["cases"][0])
        follow_up = next(
            row
            for row in private_manifest["cases"]
            if row["scenario"]["conversation_style"] == "follow_up_refinement"
        )
        tool_calls = [turn["tool_call"] for turn in follow_up["trajectory"] if "tool_call" in turn]
        self.assertEqual(len(tool_calls), 2)
        self.assertNotEqual(
            tool_calls[0]["arguments"],
            tool_calls[1]["arguments"],
        )
        self.assertTrue(
            first["safe_outputs"]["stateful_trajectory_summary"]["rendered_variants_only"]
        )
        self.assertEqual(
            (temp_dir / "private-first").stat().st_mode & 0o777,
            0o700,
        )
        self.assertEqual(
            (temp_dir / "private-first" / module.PRIVATE_MANIFEST_FILENAME).stat().st_mode & 0o777,
            0o600,
        )
        self.assertEqual(
            (temp_dir / "private-first" / module.PRIVATE_ROWS_FILENAME).stat().st_mode & 0o777,
            0o600,
        )

        rendered = json.dumps(first, sort_keys=True).lower()
        self.assertNotIn("private owner query", rendered)
        self.assertNotIn("observation-owner-1", rendered)
        self.assertNotIn("message-private", rendered)
        self.assertNotIn("query_text", rendered)
        self.assertNotIn('"trajectory":', rendered)

    def test_validator_recomputes_rows_and_aggregates(self) -> None:
        module = _load_eval_module()
        context = _valid_context(module, "mail-chatgpt-mcp-50k-derived")
        report = context["report"]
        context["private_rows_payload"]["rows"][0]["arm_results"][1]["retrieval_status"] = "passed"
        report["safe_outputs"]["arm_aggregates"][1]["case_count"] -= 1

        validation = module.validate_report(report, **context["validation_kwargs"])

        self.assertFalse(validation["passed"])
        self.assertIn("private rows result row hash mismatch", validation["blockers"])
        self.assertIn(
            "private row 0 arm results do not match source reports",
            validation["blockers"],
        )
        self.assertIn("private row 0 public row hash mismatch", validation["blockers"])
        self.assertIn("arm aggregates do not match public rows", validation["blockers"])

    def test_validator_detects_hash_tampering_even_when_status_is_unchanged(self) -> None:
        module = _load_eval_module()
        context = _valid_context(module, "mail-chatgpt-mcp-50k-tamper")
        report = context["report"]
        context["private_rows_payload"]["rows"][0]["public_row_hash"] = "sha256:" + "0" * 64

        validation = module.validate_report(report, **context["validation_kwargs"])

        self.assertFalse(validation["passed"])
        self.assertIn("private row 0 public row hash mismatch", validation["blockers"])

    def test_source_rebuild_rejects_coherently_rehashed_grounded_rows(self) -> None:
        module = _load_eval_module()
        persisted = {
            "evaluation_type": "reviewer_case_bound_evidence_derived_answer_support",
            "unique_evidence_case_count": 100,
            "rows_root_hash": sha256_json([]),
            "arm_aggregates": [],
            "rows": [],
        }
        rebuilt = {**persisted, "rows_root_hash": sha256_json(["source-rebuilt"])}
        blockers: list[str] = []

        module._validate_grounded_answer_evaluation(
            {"grounded_answer_evaluation": {"executed": True}},
            {"grounded_structured_answer_scoring_completed": True},
            private_rows_payload={"grounded_answer_evaluation": persisted},
            expected_unique_evidence_count=100,
            expected_grounded_answer_evaluation=rebuilt,
            blockers=blockers,
        )

        self.assertIn(
            "grounded answer evaluation does not match source rebuild",
            blockers,
        )

    def test_standalone_validator_rebuilds_grounded_rows_from_sources(self) -> None:
        module = _load_eval_module("mail_chatgpt_mcp_standalone_source_rebuild")
        temp_dir = _paths.fresh_test_dir("mail-chatgpt-mcp-source-rebuild")
        report_path = temp_dir / "report.json"
        output_path = temp_dir / "validation.json"
        report = {"safe_outputs": {"unique_evidence_case_count": 100}}
        report_path.write_text(json.dumps(report))
        cases = [
            _private_case(
                case_id=f"case-{index}",
                query=f"query {index}",
                result_kind="owner_match",
                required_ids=[],
            )
            for index in range(100)
        ]
        sources = module.SourceBundle(
            manifest={"cases": cases},
            baseline={},
            kg_fusion={},
            ontology_ablation={},
            ontology_factorial={},
        )
        replay = SimpleNamespace(
            attestation_hash=sha256_json("replay"),
            unique_evidence_case_count=100,
            public_rows=tuple({"case_fingerprint": case["private_fingerprint"]} for case in cases),
        )
        rebuilt = {"source": "bundle-replay-manifest"}
        private_manifest_payload = {"artifact_type": "private-manifest"}
        private_rows_payload = {"artifact_type": "private-rows"}

        with (
            mock.patch.object(module, "load_replay_artifact", return_value=replay),
            mock.patch.object(module, "_load_and_validate_sources", return_value=sources),
            mock.patch.object(
                module,
                "load_or_rebuild_may_mail_evidence_bundle",
                return_value=object(),
            ) as load_bundle,
            mock.patch.object(
                module,
                "_build_grounded_answer_evaluation",
                return_value=rebuilt,
            ) as build_grounded,
            mock.patch.object(
                module,
                "_read_json",
                side_effect=[report, private_manifest_payload, private_rows_payload],
            ),
            mock.patch.object(
                module,
                "validate_report",
                return_value={"passed": True, "blockers": []},
            ) as validate,
        ):
            exit_code = module.main(
                [
                    "--validate-report",
                    str(report_path),
                    "--output",
                    str(output_path),
                    "--private-dir",
                    str(temp_dir / "private"),
                    "--corpus-root",
                    str(temp_dir / "corpus"),
                    "--replay-cache",
                    str(temp_dir / "replay.json"),
                    "--bundle-cache",
                    str(temp_dir / "bundle.json"),
                ]
            )

        self.assertEqual(exit_code, 0)
        load_bundle.assert_called_once()
        build_grounded.assert_called_once()
        self.assertEqual(
            validate.call_args.kwargs["expected_grounded_answer_evaluation"],
            rebuilt,
        )

    def test_blocks_without_opt_in_and_on_manifest_binding_mismatch(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-chatgpt-mcp-50k-blocked")
        inputs = _write_synthetic_inputs(module, temp_dir)
        old_value = os.environ.pop(module.RUN_OPT_IN_ENV, None)
        try:
            missing_opt_in = module.run_chatgpt_mcp_50000_eval(
                **inputs,
                private_dir=temp_dir / "private",
                expected_base_case_count=3,
            )
            os.environ[module.RUN_OPT_IN_ENV] = "1"
            kg_report = json.loads(inputs["kg_fusion_report_path"].read_text())
            kg_report["safe_outputs"]["private_manifest_hash"] = "sha256:" + "f" * 64
            inputs["kg_fusion_report_path"].write_text(json.dumps(kg_report))
            binding_mismatch = module.run_chatgpt_mcp_50000_eval(
                **inputs,
                private_dir=temp_dir / "private",
                expected_base_case_count=3,
            )
        finally:
            if old_value is None:
                os.environ.pop(module.RUN_OPT_IN_ENV, None)
            else:
                os.environ[module.RUN_OPT_IN_ENV] = old_value

        self.assertEqual(
            missing_opt_in["metrics"]["blocked_reason"],
            "offline_eval_requires_explicit_opt_in",
        )
        self.assertEqual(
            binding_mismatch["metrics"]["blocked_reason"],
            "source_manifest_hash_mismatch",
        )
        self.assertTrue(missing_opt_in["validation"]["passed"])
        self.assertTrue(binding_mismatch["validation"]["passed"])

    def test_raw_leak_guard_rejects_private_fields_without_echoing_values(self) -> None:
        module = _load_eval_module()
        report = _valid_report(module, "mail-chatgpt-mcp-50k-leak")
        report["safe_outputs"]["query_text"] = "mail body secret"
        report["safe_outputs"]["message_id"] = "message-private"

        validation = module.validate_report(report)

        self.assertFalse(validation["passed"])
        rendered = json.dumps(validation, sort_keys=True).lower()
        self.assertNotIn("mail body secret", rendered)
        self.assertNotIn("message-private", rendered)
        self.assertIn("public report contains forbidden private field", validation["blockers"])

    def test_retrieval_is_separate_from_unscored_answer_usefulness(self) -> None:
        module = _load_eval_module()
        report = _valid_report(module, "mail-chatgpt-mcp-50k-quality")
        aggregates = {item["arm"]: item for item in report["safe_outputs"]["arm_aggregates"]}
        no_tool = aggregates[module.CHATGPT_WITHOUT_FORMOWL]
        mail = aggregates[module.CHATGPT_WITH_MAIL_EVIDENCE]
        kg = aggregates[module.CHATGPT_WITH_CANDIDATE_KG]
        ontology = aggregates[module.CHATGPT_WITH_ONTOLOGY_GUIDED_KG]

        self.assertEqual(no_tool["tool_call_count_total"], 0)
        self.assertEqual(
            no_tool["status_aggregates"]["overall"]["passed_count"],
            0,
        )
        self.assertEqual(
            no_tool["status_aggregates"]["overall"]["not_applicable_count"],
            no_tool["case_count"],
        )
        self.assertGreater(
            mail["status_aggregates"]["retrieval"]["passed_count"],
            no_tool["status_aggregates"]["retrieval"]["passed_count"],
        )
        self.assertGreaterEqual(
            kg["status_aggregates"]["retrieval"]["passed_count"],
            mail["status_aggregates"]["retrieval"]["passed_count"],
        )
        self.assertEqual(
            ontology["status_aggregates"]["retrieval"]["passed_count"],
            kg["status_aggregates"]["retrieval"]["passed_count"],
        )
        self.assertFalse(report["claim_boundary"]["supports_live_chatgpt_quality_claim"])
        self.assertTrue(
            report["claim_boundary"][
                "supports_deterministic_model_free_chatgpt_mcp_simulation_claim"
            ]
        )

    def test_answer_statuses_come_from_structured_oracle_not_retrieval(self) -> None:
        module = _load_eval_module()
        scenario = {
            "persona": "procurement_manager",
            "urgency": "routine",
            "answer_format": "brief",
            "conversation_style": "single_turn",
        }
        failed_score = {
            "outcome_correct": True,
            "safe_response": True,
            "overall_score": 0.5,
            "dimensions": {
                name: {
                    "matched": 0,
                    "expected": 1,
                    "predicted": 1,
                    "precision": 0.0,
                    "recall": 0.0,
                    "f1": 0.0,
                    "applicable": True,
                }
                for name in (
                    "citations",
                    "open_blockers",
                    "responsible_parties",
                    "deadlines",
                    "deadline_disclosure",
                    "next_actions",
                    "action_links",
                    "dependencies",
                    "uncertainties",
                )
            },
        }
        result = module._simulate_arm(
            arm=module.CHATGPT_WITH_MAIL_EVIDENCE,
            result_kind="owner_match",
            scenario=scenario,
            scenario_index=0,
            source_row={"status": "passed", "elapsed_ms": 1},
            structured_score=failed_score,
            tool_selection_status="passed",
            argument_contract_status="passed",
            trajectory=module._private_trajectory(
                "private owner query",
                "private owner query",
                scenario,
                actual_result_kind="owner_match",
            ),
        )

        self.assertEqual(result["retrieval_status"], "passed")
        self.assertEqual(result["final_answer_status"], "failed")
        self.assertEqual(result["citation_status"], "failed")
        self.assertEqual(result["actionability_status"], "failed")
        self.assertEqual(result["structured_answer_overall_score_micro"], 500_000)

    def test_prediction_result_kind_comes_from_actual_arm_evidence(self) -> None:
        module = _load_eval_module()

        self.assertEqual(
            module._prediction_result_kind(
                arm=module.CHATGPT_WITH_MAIL_EVIDENCE,
                selected_ids=("observation-false-positive",),
                mail_result_kind="owner_match",
                permission_denied=False,
            ),
            "owner_match",
        )
        self.assertEqual(
            module._prediction_result_kind(
                arm=module.CHATGPT_WITH_MAIL_EVIDENCE,
                selected_ids=(),
                mail_result_kind="no_match",
                permission_denied=False,
            ),
            "no_match",
        )
        self.assertEqual(
            module._prediction_result_kind(
                arm=module.CHATGPT_WITH_CANDIDATE_KG,
                selected_ids=("observation-false-positive",),
                mail_result_kind="no_match",
                permission_denied=False,
            ),
            "owner_match",
        )
        self.assertEqual(
            module._prediction_result_kind(
                arm=module.CHATGPT_WITH_ONTOLOGY_GUIDED_KG,
                selected_ids=("observation-private",),
                mail_result_kind="owner_match",
                permission_denied=True,
            ),
            "permission_denied",
        )

    def test_structured_score_average_preserves_micro_scale(self) -> None:
        module = _load_eval_module()

        self.assertEqual(module._micro_average(1_000_000, 2), 500_000)
        self.assertEqual(module._micro_average(7_378_990, 80), 92_237)
        self.assertEqual(module._micro_average(0, 0), 0)

    def test_rendered_tool_calls_are_validated_against_bound_schema(self) -> None:
        module = _load_eval_module()
        scenario = {
            "persona": "procurement_manager",
            "urgency": "routine",
            "answer_format": "brief",
            "conversation_style": "single_turn",
        }
        trajectory = module._private_trajectory(
            "supplier delay",
            module._private_user_query("supplier delay", scenario),
            scenario,
            actual_result_kind="owner_match",
        )
        tools_list = module._simulation_tools_list_response()
        self.assertEqual(
            module._trajectory_contract_statuses(trajectory, tools_list),
            ("passed", "passed"),
        )

        mutations = []
        unknown_tool = json.loads(json.dumps(trajectory))
        unknown_tool[1]["tool_call"]["name"] = "unknown_tool"
        mutations.append((unknown_tool, ("failed", "failed")))
        missing_selector = json.loads(json.dumps(trajectory))
        missing_selector[1]["tool_call"]["arguments"].pop("mail_import_session_id")
        mutations.append((missing_selector, ("passed", "failed")))
        extra_field = json.loads(json.dumps(trajectory))
        extra_field[1]["tool_call"]["arguments"]["requester_user_id"] = "caller"
        mutations.append((extra_field, ("passed", "failed")))
        invalid_limit = json.loads(json.dumps(trajectory))
        invalid_limit[1]["tool_call"]["arguments"]["limit"] = 101
        mutations.append((invalid_limit, ("passed", "failed")))

        for mutated, expected in mutations:
            with self.subTest(expected=expected):
                self.assertEqual(
                    module._trajectory_contract_statuses(mutated, tools_list),
                    expected,
                )

    def test_conversation_styles_are_distinct_and_response_conditional(self) -> None:
        module = _load_eval_module()
        base = {
            "persona": "procurement_manager",
            "urgency": "urgent",
            "answer_format": "action_plan",
        }
        query = "supplier delay"
        single_scenario = {**base, "conversation_style": "single_turn"}
        clarification_scenario = {**base, "conversation_style": "clarification_then_tool"}
        correction_scenario = {**base, "conversation_style": "correction_after_no_match"}
        single = module._private_trajectory(
            query,
            module._private_user_query(query, single_scenario),
            single_scenario,
            actual_result_kind="owner_match",
        )
        clarification = module._private_trajectory(
            query,
            module._private_user_query(query, clarification_scenario),
            clarification_scenario,
            actual_result_kind="owner_match",
        )
        correction_not_triggered = module._private_trajectory(
            query,
            module._private_user_query(query, correction_scenario),
            correction_scenario,
            actual_result_kind="owner_match",
        )
        correction_triggered = module._private_trajectory(
            query,
            module._private_user_query(query, correction_scenario),
            correction_scenario,
            actual_result_kind="no_match",
        )

        self.assertNotEqual(single, clarification)
        self.assertTrue(module._trajectory_has_clarification(clarification))
        self.assertEqual(len(module._trajectory_tool_calls(single)), 1)
        self.assertEqual(len(module._trajectory_tool_calls(correction_not_triggered)), 1)
        self.assertEqual(len(module._trajectory_tool_calls(correction_triggered)), 2)
        self.assertFalse(module._trajectory_condition(correction_not_triggered)["triggered"])
        self.assertTrue(module._trajectory_condition(correction_triggered)["triggered"])
        self.assertEqual(
            module._trajectory_tool_calls(single)[0]["arguments"]["query_text"],
            query,
        )
        self.assertNotIn("procurement manager", query)

    def test_non_triggered_condition_does_not_add_tool_call_or_turn_cost(self) -> None:
        module = _load_eval_module()
        scenario = {
            "persona": "procurement_manager",
            "urgency": "routine",
            "answer_format": "brief",
            "conversation_style": "correction_after_no_match",
        }
        non_triggered = module._private_trajectory(
            "private owner query",
            "rendered owner query",
            scenario,
            actual_result_kind="owner_match",
        )
        triggered = module._private_trajectory(
            "private no match query",
            "rendered no match query",
            scenario,
            actual_result_kind="no_match",
        )
        common = {
            "arm": module.CHATGPT_WITH_MAIL_EVIDENCE,
            "result_kind": "no_match",
            "scenario": scenario,
            "scenario_index": 0,
            "source_row": {"status": "failed", "elapsed_ms": 1},
            "structured_score": None,
            "tool_selection_status": "passed",
            "argument_contract_status": "passed",
        }

        non_triggered_result = module._simulate_arm(
            **common,
            trajectory=non_triggered,
        )
        triggered_result = module._simulate_arm(
            **common,
            trajectory=triggered,
        )

        self.assertEqual(non_triggered_result["tool_call_count"], 1)
        self.assertEqual(non_triggered_result["trajectory_turn_count"], len(non_triggered))
        self.assertEqual(triggered_result["tool_call_count"], 2)
        self.assertEqual(triggered_result["trajectory_turn_count"], len(triggered))
        self.assertLess(
            non_triggered_result["simulated_cost_ms"],
            triggered_result["simulated_cost_ms"],
        )

    def test_factorial_binding_is_aggregate_only_and_compares_major_arms(self) -> None:
        module = _load_eval_module()
        report = _valid_report(module, "mail-chatgpt-mcp-50k-factorial")
        factorial = report["safe_outputs"]["factorial_aggregate_summary"]

        self.assertEqual(factorial["arm_count"], 326)
        self.assertFalse(factorial["per_case_factorial_rows_available"])
        self.assertFalse(factorial["per_case_factorial_rows_synthesized"])
        self.assertEqual(factorial["best"]["base_passed_case_count"], 3)
        self.assertEqual(factorial["best"]["projected_expanded_passed_case_count"], 12)
        self.assertIn("operator_order", factorial["best"])
        self.assertIn("source_measured_elapsed_ms", factorial["median"])
        self.assertIn("source_measured_elapsed_ms", factorial["worst"])
        self.assertEqual(factorial["best"]["operator_count"], 0)
        self.assertEqual(
            factorial["best_retrieval_delta_vs_major_arms_base_case_count"][
                module.CHATGPT_WITH_CANDIDATE_KG
            ],
            1,
        )
        self.assertEqual(factorial["comparison_basis"], "retrieval_passed_case_count")
        self.assertEqual(factorial["major_arm_status_key"], "retrieval_status")
        self.assertEqual(
            factorial["retrieval_arms_better_than_candidate_kg_count"]
            + factorial["retrieval_arms_equal_to_candidate_kg_count"]
            + factorial["retrieval_arms_worse_than_candidate_kg_count"],
            326,
        )
        self.assertNotIn("arms_better_than_candidate_kg_count", factorial)
        rendered = json.dumps(report, sort_keys=True).lower()
        self.assertNotIn("factorial_case_rows", rendered)

    def test_private_writer_rejects_symlink_target(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-chatgpt-mcp-50k-symlink")
        private_dir = temp_dir / "private"
        private_dir.mkdir()
        destination = temp_dir / "outside.json"
        destination.write_text("unchanged")
        (private_dir / module.PRIVATE_MANIFEST_FILENAME).symlink_to(destination)

        with self.assertRaisesRegex(RuntimeError, "symlink"):
            module._write_private_artifacts_atomic(
                private_dir,
                {
                    module.PRIVATE_MANIFEST_FILENAME: {"secret": "value"},
                    module.PRIVATE_ROWS_FILENAME: {"rows": []},
                },
            )

        self.assertEqual(destination.read_text(), "unchanged")
        self.assertFalse((private_dir / module.PRIVATE_ROWS_FILENAME).exists())

    def test_private_writer_rolls_back_both_artifacts_on_replace_failure(self) -> None:
        module = _load_eval_module()
        temp_dir = _paths.fresh_test_dir("mail-chatgpt-mcp-50k-rollback")
        private_dir = temp_dir / "private"
        module._write_private_artifacts_atomic(
            private_dir,
            {
                module.PRIVATE_MANIFEST_FILENAME: {"version": "old"},
                module.PRIVATE_ROWS_FILENAME: {"version": "old"},
            },
        )
        original_replace = module.os.replace
        install_count = 0

        def failing_replace(source, destination):
            nonlocal install_count
            if str(source).endswith(".tmp"):
                install_count += 1
                if install_count == 2:
                    raise OSError("injected second install failure")
            return original_replace(source, destination)

        with mock.patch.object(module.os, "replace", side_effect=failing_replace):
            with self.assertRaisesRegex(OSError, "injected"):
                module._write_private_artifacts_atomic(
                    private_dir,
                    {
                        module.PRIVATE_MANIFEST_FILENAME: {"version": "new"},
                        module.PRIVATE_ROWS_FILENAME: {"version": "new"},
                    },
                )

        for filename in (module.PRIVATE_MANIFEST_FILENAME, module.PRIVATE_ROWS_FILENAME):
            self.assertEqual(json.loads((private_dir / filename).read_text()), {"version": "old"})
        self.assertEqual(list(private_dir.glob(".*.tmp")), [])
        self.assertEqual(list(private_dir.glob(".*.bak")), [])


def _valid_report(module, name: str):
    return _valid_context(module, name)["report"]


def _valid_context(module, name: str):
    temp_dir = _paths.fresh_test_dir(name)
    inputs = _write_synthetic_inputs(module, temp_dir)
    dimensions = module.ExpansionDimensions(
        personas=("manager", "reviewer"),
        urgencies=("routine",),
        answer_formats=("brief",),
        conversation_styles=("single_turn", "follow_up_refinement"),
    )
    private_dir = temp_dir / "private"
    report = _run_with_opt_in(
        module,
        inputs=inputs,
        private_dir=private_dir,
        dimensions=dimensions,
    )
    private_manifest_payload = json.loads(
        (private_dir / module.PRIVATE_MANIFEST_FILENAME).read_text()
    )
    private_rows_payload = json.loads((private_dir / module.PRIVATE_ROWS_FILENAME).read_text())
    sources = module._load_and_validate_sources(
        **inputs,
        expected_base_case_count=3,
    )
    return {
        "report": report,
        "private_manifest_payload": private_manifest_payload,
        "private_rows_payload": private_rows_payload,
        "sources": sources,
        "private_dir": private_dir,
        "validation_kwargs": {
            "private_manifest_payload": private_manifest_payload,
            "private_rows_payload": private_rows_payload,
            "sources": sources,
            "private_dir": private_dir,
        },
    }


def _run_with_opt_in(module, *, inputs, private_dir, dimensions):
    old_value = os.environ.get(module.RUN_OPT_IN_ENV)
    os.environ[module.RUN_OPT_IN_ENV] = "1"
    try:
        return module.run_chatgpt_mcp_50000_eval(
            **inputs,
            private_dir=private_dir,
            dimensions=dimensions,
            expected_base_case_count=3,
        )
    finally:
        if old_value is None:
            os.environ.pop(module.RUN_OPT_IN_ENV, None)
        else:
            os.environ[module.RUN_OPT_IN_ENV] = old_value


def _write_synthetic_inputs(module, temp_dir: Path):
    manifest = {
        "manifest_type": "mail_full_pst_domain_hard_case_manifest_private",
        "case_count": 3,
        "cases": [
            _private_case(
                case_id="case-owner",
                query="private owner query",
                result_kind="owner_match",
                required_ids=["observation-owner-1", "observation-owner-2"],
            ),
            _private_case(
                case_id="case-no-match",
                query="private no match query",
                result_kind="no_match",
                required_ids=[],
            ),
            _private_case(
                case_id="case-permission",
                query="private permission query",
                result_kind="permission_denied",
                required_ids=[],
                forbidden_ids=["message-private"],
            ),
        ],
    }
    manifest_hash = sha256_json(manifest)
    fingerprints = [case["private_fingerprint"] for case in manifest["cases"]]
    baseline_rows = [
        _baseline_row(fingerprints[0], "owner_match", "failed", citations=0, elapsed=11),
        _baseline_row(fingerprints[1], "no_match", "passed", citations=0, elapsed=7),
        _baseline_row(
            fingerprints[2],
            "permission_denied",
            "passed",
            citations=0,
            elapsed=5,
        ),
    ]
    kg_rows = [
        _kg_row(fingerprints[0], "owner_match", "passed", selected=2, elapsed=3),
        _kg_row(fingerprints[1], "no_match", "failed", selected=0, elapsed=2),
        _kg_row(fingerprints[2], "permission_denied", "passed", selected=0, elapsed=2),
    ]
    ontology_rows = [
        _ontology_row(fingerprints[0], "owner_match", "passed", selected=2, elapsed=4),
        _ontology_row(fingerprints[1], "no_match", "failed", selected=0, elapsed=3),
        _ontology_row(
            fingerprints[2],
            "permission_denied",
            "passed",
            selected=0,
            elapsed=3,
        ),
    ]
    factorial_summaries = [_factorial_summary(index) for index in range(326)]

    manifest_path = temp_dir / "manifest.private.json"
    baseline_path = temp_dir / "baseline.json"
    kg_path = temp_dir / "kg.json"
    ontology_path = temp_dir / "ontology.json"
    factorial_path = temp_dir / "factorial.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    baseline_path.write_text(
        json.dumps(
            {
                "report_type": "baseline",
                "safe_outputs": {
                    "private_manifest_hash": manifest_hash,
                    "case_rows": baseline_rows,
                },
            },
            sort_keys=True,
        )
    )
    kg_path.write_text(
        json.dumps(
            {
                "report_type": "kg_fusion",
                "safe_outputs": {
                    "private_manifest_hash": manifest_hash,
                    "case_rows": kg_rows,
                },
            },
            sort_keys=True,
        )
    )
    ontology_path.write_text(
        json.dumps(
            {
                "report_type": "ontology_ablation",
                "safe_outputs": {
                    "private_manifest_hash": manifest_hash,
                    "ablation_rows": ontology_rows,
                },
            },
            sort_keys=True,
        )
    )
    factorial_path.write_text(
        json.dumps(
            {
                "report_type": "ontology_factorial",
                "safe_outputs": {
                    "private_manifest_hash": manifest_hash,
                    "arm_summaries": factorial_summaries,
                },
            },
            sort_keys=True,
        )
    )
    return {
        "private_manifest_path": manifest_path,
        "baseline_report_path": baseline_path,
        "kg_fusion_report_path": kg_path,
        "ontology_ablation_report_path": ontology_path,
        "ontology_factorial_report_path": factorial_path,
    }


def _private_case(
    *,
    case_id: str,
    query: str,
    result_kind: str,
    required_ids: list[str],
    forbidden_ids: list[str] | None = None,
):
    return {
        "case_id": case_id,
        "domain": "procurement",
        "intent_kind": "review",
        "pattern": "synthetic",
        "query_text": query,
        "requester_user_id": "user-reviewer",
        "result_kind": result_kind,
        "required_match_count": len(required_ids),
        "required_source_observation_ids": required_ids,
        "forbidden_source_observation_ids": forbidden_ids or [],
        "private_fingerprint": sha256_json(
            {"case_id": case_id, "query": query, "result_kind": result_kind}
        ),
    }


def _baseline_row(fingerprint, result_kind, status, *, citations, elapsed):
    return {
        "case_manifest_entry_hash": fingerprint,
        "result_kind": result_kind,
        "status": status,
        "citation_count": citations,
        "elapsed_ms": elapsed,
        "response_hash": sha256_json([fingerprint, "baseline", status]),
    }


def _kg_row(fingerprint, result_kind, status, *, selected, elapsed):
    return {
        "case_manifest_entry_hash": fingerprint,
        "result_kind": result_kind,
        "kg_status": status,
        "selected_evidence_count": selected,
        "elapsed_ms": elapsed,
        "response_hash": sha256_json([fingerprint, "kg", status]),
    }


def _ontology_row(fingerprint, result_kind, status, *, selected, elapsed):
    return {
        "case_manifest_entry_hash": fingerprint,
        "result_kind": result_kind,
        "ontology_status": status,
        "ontology_selected_evidence_count": selected,
        "ontology_elapsed_ms": elapsed,
        "ontology_response_hash": sha256_json([fingerprint, "ontology", status]),
    }


def _factorial_summary(index: int):
    passed = 3 if index in {0, 325} else 2 if index % 5 == 0 else 1 if index % 2 == 0 else 0
    operator_order = [] if index == 0 else [f"operator_{index % 5}"]
    without_hash = {
        "arm_id_hash": sha256_json(["factorial-arm", index]),
        "case_result_hash": sha256_json(["factorial-results", index]),
        "elapsed_ms": index + 1,
        "failed_case_count": 3 - passed,
        "no_match_passed_count": 0,
        "operator_count": len(operator_order),
        "operator_order": operator_order,
        "pass_rate_basis_points": int((passed / 3) * 10_000),
        "passed_case_count": passed,
        "permission_denied_passed_count": 1 if passed else 0,
        "positive_passed_count": 1 if passed > 1 else 0,
        "unique_response_hash_count": 3,
    }
    return {**without_hash, "arm_summary_hash": sha256_json(without_hash)}


if __name__ == "__main__":
    unittest.main()
