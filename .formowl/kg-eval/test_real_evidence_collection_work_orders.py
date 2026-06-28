#!/usr/bin/env python3
"""Tests for real-evidence collection work-order generation."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import real_evidence_collection_work_orders as work_orders
import real_evidence_preflight as preflight


def nested_keys(payload: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                keys.add(key)
            keys.update(nested_keys(value))
    elif isinstance(payload, list):
        for value in payload:
            keys.update(nested_keys(value))
    return keys


def nested_strings(payload: object) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(key, str):
                values.append(key)
            values.extend(nested_strings(value))
    elif isinstance(payload, list):
        for value in payload:
            values.extend(nested_strings(value))
    elif isinstance(payload, str):
        values.append(payload)
    return values


def snapshot_files(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def snapshot_tree(root: Path) -> dict[Path, bytes | str]:
    if not root.exists():
        return {root: "<missing>"}
    snapshot: dict[Path, bytes | str] = {root: "<dir>"}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            snapshot[relative] = f"<symlink:{path.readlink()}>"
        elif path.is_file():
            snapshot[relative] = path.read_bytes()
        elif path.is_dir():
            snapshot[relative] = "<dir>"
        else:
            snapshot[relative] = "<other>"
    return snapshot


def load_json(path: Path) -> dict:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


class RealEvidenceCollectionWorkOrdersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot_bytes = (
            work_orders.RESULTS / "kg_total_acceptance_snapshot.json"
        ).read_bytes()
        self.objective_audit_bytes = (
            work_orders.RESULTS / "kg_objective_completion_audit.json"
        ).read_bytes()
        self.preflight_bytes = (work_orders.RESULTS / "real_evidence_preflight.json").read_bytes()
        self.canonical_packet_paths = [
            gate["input_packet"] for gate in preflight.EXPECTED_GATES.values()
        ]
        self.template_paths = [gate["template"] for gate in preflight.EXPECTED_GATES.values()]
        self.real_root_state = {
            gate_id: sorted(
                path.relative_to(work_orders.ROOT) for path in gate["real_root"].rglob("*")
            )
            for gate_id, gate in preflight.EXPECTED_GATES.items()
        }

    def tearDown(self) -> None:
        (work_orders.RESULTS / "kg_total_acceptance_snapshot.json").write_bytes(self.snapshot_bytes)
        (work_orders.RESULTS / "kg_objective_completion_audit.json").write_bytes(
            self.objective_audit_bytes
        )
        (work_orders.RESULTS / "real_evidence_preflight.json").write_bytes(self.preflight_bytes)

    def _order(self, report: dict, gate_id: str) -> dict:
        return {row["gate_id"]: row for row in report["work_orders"]}[gate_id]

    def test_work_orders_cover_exact_remaining_gates_and_are_non_authoritative(self) -> None:
        report = work_orders.build_report()

        self.assertEqual(
            report["work_order_state"], "collection_blocked_until_real_evidence_exists"
        )
        self.assertFalse(report["work_order_authority"]["accepts_evidence"])
        self.assertFalse(report["work_order_authority"]["promotes_evidence"])
        self.assertFalse(report["work_order_authority"]["writes_assembly_manifests"])
        self.assertFalse(report["work_order_authority"]["writes_canonical_packets"])
        self.assertFalse(report["work_order_authority"]["counts_as_acceptance_gate"])
        self.assertFalse(report["work_order_authority"]["replaces_authoritative_validators"])
        self.assertNotIn("overall_ready", report)
        self.assertNotIn("claim_boundary", report)
        keys = nested_keys(report)
        strings = nested_strings(report)
        self.assertNotIn("passed", keys)
        self.assertNotIn("overall_ready", keys)
        self.assertNotIn("ready_for_acceptance", keys)
        self.assertNotIn("claim_boundary", keys)
        self.assertFalse(any(key.startswith("supports_") for key in keys))
        self.assertFalse(any(value == "passed" for value in strings))
        self.assertFalse(any("supports_" in value for value in strings))
        self.assertFalse(any("--promote" in value for value in strings))
        self.assertEqual(
            report["summary"]["work_order_gate_ids"],
            [
                "fair_external_baseline_comparison",
                "annotation_adjudication_protocol",
                "multimodal_semantic_validation",
                "production_adapter_paths",
            ],
        )
        self.assertEqual(
            report["summary"]["work_order_gate_ids"],
            report["summary"]["preflight_blocked_gate_ids"],
        )
        self.assertEqual(report["sync"]["status"], "synchronized")
        self.assertFalse(report["sync"]["normal_work_orders_withheld"])

    def test_work_orders_stay_synchronized_with_checklist_and_preflight(self) -> None:
        checklist = work_orders.load_json(work_orders.CHECKLIST_PATH)
        preflight_report = preflight.build_report()
        preflight_by_gate = {row["gate_id"]: row for row in preflight_report["gates"]}
        report = work_orders.build_report()

        checklist_by_gate = {row["gate_id"]: row for row in checklist["remaining_gates"]}
        for gate_id, checklist_row in checklist_by_gate.items():
            with self.subTest(gate_id=gate_id):
                order = self._order(report, gate_id)
                gate_config = preflight.EXPECTED_GATES[gate_id]
                preflight_row = preflight_by_gate[gate_id]

                self.assertEqual(order["requirement_id"], checklist_row["requirement_id"])
                self.assertEqual(order["canonical_input_packet"], checklist_row["input_packet"])
                self.assertEqual(
                    order["required_packet_artifact_id"],
                    checklist_row["required_packet_artifact_id"],
                )
                self.assertEqual(
                    order["required_evidence_kind"], checklist_row["required_evidence_kind"]
                )
                self.assertEqual(order["real_artifact_root"], gate_config["real_root_rel"])
                self.assertEqual(order["validator_module"], checklist_row["validator_module"])
                self.assertEqual(order["assembler_module"], gate_config["assembler_module"])
                self.assertEqual(order["current_blockers"], checklist_row["current_blockers"])
                self.assertEqual(order["collection_status"], preflight_row["collection_state"])
                self.assertEqual(order["preflight_snapshot"]["validator_status"], "blocked")
                self.assertEqual(order["preflight_snapshot"]["current_total_gate_state"], "blocked")
                self.assertEqual(
                    order["preflight_snapshot"]["packet_state"],
                    preflight_row["packet_surface"]["packet_state"],
                )
                self.assertFalse(order["preflight_snapshot"]["root_ready"])
                self.assertEqual(order["preflight_snapshot"]["real_root_file_count"], 0)
                self.assertEqual(
                    order["preflight_snapshot"]["real_root_candidate_artifact_count"], 0
                )
                self.assertEqual(order["preflight_snapshot"]["real_root_disappeared_file_count"], 0)
                self.assertEqual(
                    order["preflight_snapshot"]["real_root_disappeared_file_count"],
                    preflight_row["real_root_scan"]["disappeared_file_count"],
                )

    def test_current_baseline_visibly_remains_missing_real_evidence(self) -> None:
        report = work_orders.build_report()

        self.assertEqual(
            report["work_order_state"], "collection_blocked_until_real_evidence_exists"
        )
        for row in report["work_orders"]:
            with self.subTest(gate_id=row["gate_id"]):
                snapshot = row["preflight_snapshot"]
                self.assertEqual(row["collection_status"], "missing_real_artifacts_and_packet")
                self.assertEqual(snapshot["validator_status"], "blocked")
                self.assertEqual(snapshot["packet_state"], "missing")
                self.assertEqual(snapshot["root_ready"], False)
                self.assertEqual(snapshot["real_root_file_count"], 0)
                self.assertEqual(snapshot["real_root_candidate_artifact_count"], 0)
                self.assertEqual(snapshot["real_root_disappeared_file_count"], 0)

    def test_checklist_or_preflight_drift_fails_closed_without_normal_work_orders(self) -> None:
        checklist = work_orders.load_json(work_orders.CHECKLIST_PATH)
        drifted_checklist = deepcopy(checklist)
        drifted_checklist["remaining_gates"] = drifted_checklist["remaining_gates"][:-1]

        checklist_report = work_orders.build_report(checklist_override=drifted_checklist)

        self.assertEqual(checklist_report["sync"]["status"], "drifted")
        self.assertTrue(checklist_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(
            checklist_report["work_order_state"],
            "withheld_due_to_checklist_or_preflight_drift",
        )
        self.assertEqual(checklist_report["summary"]["work_order_count"], 0)
        self.assertEqual(checklist_report["work_orders"], [])

        drifted_preflight = preflight.build_report()
        drifted_preflight["checklist_sync"]["status"] = "drifted"

        preflight_report = work_orders.build_report(preflight_report_override=drifted_preflight)

        self.assertEqual(preflight_report["sync"]["status"], "drifted")
        self.assertTrue(preflight_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(preflight_report["summary"]["work_order_count"], 0)
        self.assertEqual(preflight_report["work_orders"], [])

    def test_missing_or_malformed_preflight_gate_rows_fail_closed(self) -> None:
        missing_gate = preflight.build_report()
        missing_gate["gates"] = missing_gate["gates"][:-1]

        missing_report = work_orders.build_report(preflight_report_override=missing_gate)

        self.assertEqual(missing_report["sync"]["status"], "drifted")
        self.assertFalse(missing_report["sync"]["per_gate_preflight_contract_valid"])
        self.assertTrue(missing_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(missing_report["work_orders"], [])

        malformed_gate = preflight.build_report()
        malformed_gate["gates"][0].pop("packet_surface")
        malformed_gate["gates"][1]["real_root_scan"] = {
            "file_count": 0,
            "candidate_artifact_count": 0,
            "disappeared_file_count": "0",
            "root_ready": False,
        }
        malformed_gate["gates"][2]["real_root_scan"].pop("disappeared_file_count")

        malformed_report = work_orders.build_report(preflight_report_override=malformed_gate)

        self.assertEqual(malformed_report["sync"]["status"], "drifted")
        self.assertFalse(malformed_report["sync"]["per_gate_preflight_contract_valid"])
        details = malformed_report["sync"]["per_gate_preflight_contract"]["details"]
        self.assertFalse(
            details["annotation_adjudication_protocol"]["checks"][
                "real_root_disappeared_file_count_is_int"
            ]
        )
        self.assertFalse(
            details["multimodal_semantic_validation"]["checks"][
                "real_root_disappeared_file_count_is_int"
            ]
        )
        self.assertTrue(malformed_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(malformed_report["work_orders"], [])

    def test_disappeared_real_root_files_fail_closed_instead_of_collecting(self) -> None:
        unstable_preflight = preflight.build_report()
        unstable_scan = unstable_preflight["gates"][0]["real_root_scan"]
        unstable_scan["disappeared_file_count"] = 1
        unstable_scan["disappeared_file_paths"] = [
            "inputs/fair_baseline_real/operator-run/transient.json"
        ]

        report = work_orders.build_report(preflight_report_override=unstable_preflight)
        checks = report["sync"]["per_gate_preflight_contract"]["details"][
            "fair_external_baseline_comparison"
        ]["checks"]

        self.assertEqual(report["sync"]["status"], "drifted")
        self.assertFalse(report["sync"]["per_gate_preflight_contract_valid"])
        self.assertFalse(checks["current_absence_visible"])
        self.assertTrue(checks["real_root_disappeared_file_count_is_int"])
        self.assertTrue(report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(report["summary"]["work_order_count"], 0)
        self.assertEqual(report["work_orders"], [])

    def test_clear_preflight_gate_rows_fail_closed_instead_of_collecting(self) -> None:
        clear_preflight = preflight.build_report()
        for gate in clear_preflight["gates"]:
            gate["collection_state"] = "clear"
            gate["current_total_gate_state"] = "clear"
            gate["validator_status"] = "clear"
            gate["packet_surface"]["packet_state"] = "complete"
            gate["real_root_scan"]["root_ready"] = True
            gate["real_root_scan"]["file_count"] = 1
            gate["real_root_scan"]["candidate_artifact_count"] = 1

        report = work_orders.build_report(preflight_report_override=clear_preflight)

        self.assertEqual(report["sync"]["status"], "drifted")
        self.assertFalse(report["sync"]["per_gate_preflight_contract_valid"])
        self.assertTrue(report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(report["summary"]["work_order_count"], 0)
        self.assertEqual(report["work_orders"], [])

    def test_mocked_clear_validator_states_do_not_become_acceptance_claims(self) -> None:
        mocked_preflight = preflight.build_report()
        for gate in mocked_preflight["gates"]:
            gate["collection_state"] = "passed"
            gate["current_total_gate_state"] = "passed"
            gate["validator_status"] = "passed"
            gate["packet_surface"]["packet_state"] = "passed"
            gate["real_root_scan"]["root_ready"] = True
            gate["real_root_scan"]["file_count"] = 3
            gate["real_root_scan"]["candidate_artifact_count"] = 3
        mocked_preflight["summary"]["total_acceptance_state"] = "passed"

        report = work_orders.build_report(preflight_report_override=mocked_preflight)

        strings = nested_strings(report)
        self.assertFalse(report["work_order_authority"]["accepts_evidence"])
        self.assertFalse(report["work_order_authority"]["counts_as_acceptance_gate"])
        self.assertFalse(report["work_order_authority"]["replaces_authoritative_validators"])
        self.assertFalse(any(value == "passed" for value in strings))
        self.assertFalse(any("supports_" in value for value in strings))
        for row in report["work_orders"]:
            self.assertEqual(
                row["preflight_snapshot"]["validator_status"],
                "non_blocked_state_not_authoritative_in_work_order_report",
            )

    def test_gate_specific_requirements_are_not_dropped(self) -> None:
        checklist = work_orders.load_json(work_orders.CHECKLIST_PATH)
        checklist_by_gate = {row["gate_id"]: row for row in checklist["remaining_gates"]}
        report = work_orders.build_report()

        fair = self._order(report, "fair_external_baseline_comparison")
        fair_checklist = checklist_by_gate["fair_external_baseline_comparison"]
        self.assertEqual(
            [row["baseline_id"] for row in fair["operator_tasks"]["baseline_package_runs"]],
            fair_checklist["required_baselines"],
        )
        self.assertEqual(
            fair["operator_tasks"]["source_lock"]["required_source_lock_sha256"],
            fair_checklist["required_source_lock_sha256"],
        )
        self.assertTrue(fair["operator_tasks"]["source_lock"]["per_baseline_source_ids_required"])
        for row in fair["operator_tasks"]["baseline_package_runs"]:
            self.assertEqual(
                row["required_artifact_fields"], fair_checklist["required_artifacts_per_baseline"]
            )
            self.assertEqual(
                row["required_equalized_hashes"], fair_checklist["required_equalized_hashes"]
            )
            self.assertEqual(
                row["required_source_ids"],
                fair_checklist["required_source_ids_by_baseline"][row["baseline_id"]],
            )
        self.assertEqual(
            fair["operator_tasks"]["human_answer_adjudication"],
            fair_checklist["required_human_evidence"],
        )
        self.assertEqual(
            fair["operator_tasks"]["graph_quality_validation"],
            fair_checklist["required_graph_quality_evidence"],
        )
        self.assertEqual(
            fair["operator_tasks"]["permission_probe_evidence"],
            fair_checklist["required_permission_probe_evidence"],
        )
        self.assertEqual(
            fair["operator_tasks"]["run_artifact_content_contract"],
            fair_checklist["required_run_artifact_content_contract"],
        )
        self.assertIn(
            "package_lock_artifact artifact_type == fair_baseline_package_lock_v1",
            fair["operator_tasks"]["run_artifact_content_contract"],
        )
        fair_response_contract = fair["operator_tasks"]["response_packet_contract"]
        self.assertEqual(
            fair_response_contract["response_packet_type"], "fair_baseline_response_intake_v1"
        )
        self.assertEqual(
            fair_response_contract["response_packet_placeholder"],
            work_orders.FAIR_RESPONSE_PACKET_PLACEHOLDER,
        )
        self.assertEqual(
            fair_response_contract["work_packet_path"],
            work_orders.FAIR_RESPONSE_INTAKE_WORK_PACKET,
        )
        self.assertEqual(
            fair_response_contract["candidate_output_dir"],
            work_orders.FAIR_RESPONSE_INTAKE_OUTPUT_DIR,
        )
        self.assertEqual(
            fair_response_contract["assembly_manifest_output"],
            work_orders.FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT,
        )
        self.assertFalse(fair_response_contract["writes_canonical_packet"])
        self.assertEqual(
            fair_response_contract["canonical_packet_not_written"],
            fair["canonical_input_packet"],
        )
        self.assertFalse(fair_response_contract["promotes_evidence"])
        self.assertFalse(fair_response_contract["counts_as_acceptance_gate"])
        self.assertIn(
            "operator supplied real package run artifacts for every baseline",
            fair_response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds response packet, candidate packet, and artifact hashes",
            fair_response_contract["required_controls"],
        )

        human = self._order(report, "annotation_adjudication_protocol")
        human_checklist = checklist_by_gate["annotation_adjudication_protocol"]
        self.assertEqual(
            human["operator_tasks"]["required_artifacts"], human_checklist["required_artifacts"]
        )
        self.assertEqual(
            human["operator_tasks"]["human_controls"], human_checklist["required_human_controls"]
        )
        response_contract = human["operator_tasks"]["response_packet_contract"]
        self.assertEqual(
            response_contract["response_packet_type"], "human_annotation_response_intake_v1"
        )
        self.assertEqual(
            response_contract["response_packet_placeholder"],
            work_orders.HUMAN_RESPONSE_PACKET_PLACEHOLDER,
        )
        self.assertEqual(
            response_contract["work_packet_path"],
            work_orders.HUMAN_RESPONSE_INTAKE_WORK_PACKET,
        )
        self.assertEqual(
            response_contract["candidate_output_dir"],
            work_orders.HUMAN_RESPONSE_INTAKE_OUTPUT_DIR,
        )
        self.assertEqual(
            response_contract["assembly_manifest_output"],
            work_orders.HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT,
        )
        self.assertFalse(response_contract["writes_canonical_packet"])
        self.assertEqual(
            response_contract["canonical_packet_not_written"], human["canonical_input_packet"]
        )
        self.assertFalse(response_contract["promotes_evidence"])
        self.assertFalse(response_contract["counts_as_acceptance_gate"])
        self.assertIn(
            "at least one first-pass disagreement",
            response_contract["required_controls"],
        )
        self.assertIn(
            "generated_by_llm == false for every submission and adjudication row",
            response_contract["required_controls"],
        )
        self.assertIn(
            "operator_run_id matches the candidate output directory final segment",
            response_contract["required_controls"],
        )
        self.assertIn(
            "unsupported response packet fields and raw/internal field names are rejected",
            response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds response packet, candidate packet, and artifact hashes",
            response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds optional assembly manifest hash when emitted",
            response_contract["required_controls"],
        )

        enterprise = self._order(report, "multimodal_semantic_validation")
        enterprise_checklist = checklist_by_gate["multimodal_semantic_validation"]
        self.assertEqual(
            enterprise["operator_tasks"]["required_modalities"],
            enterprise_checklist["required_modalities"],
        )
        self.assertEqual(
            enterprise["operator_tasks"]["required_artifacts"],
            enterprise_checklist["required_artifacts"],
        )
        self.assertEqual(
            enterprise["operator_tasks"]["controls"], enterprise_checklist["required_controls"]
        )
        self.assertEqual(
            [row["modality"] for row in enterprise["operator_tasks"]["per_modality_rows"]],
            enterprise_checklist["required_modalities"],
        )
        enterprise_response_contract = enterprise["operator_tasks"]["response_packet_contract"]
        self.assertEqual(
            enterprise_response_contract["response_packet_type"],
            "enterprise_multimodal_response_intake_v1",
        )
        self.assertEqual(
            enterprise_response_contract["response_packet_placeholder"],
            work_orders.ENTERPRISE_RESPONSE_PACKET_PLACEHOLDER,
        )
        self.assertEqual(
            enterprise_response_contract["work_packet_path"],
            work_orders.ENTERPRISE_RESPONSE_INTAKE_WORK_PACKET,
        )
        self.assertEqual(
            enterprise_response_contract["candidate_output_dir"],
            work_orders.ENTERPRISE_RESPONSE_INTAKE_OUTPUT_DIR,
        )
        self.assertEqual(
            enterprise_response_contract["assembly_manifest_output"],
            work_orders.ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT,
        )
        self.assertFalse(enterprise_response_contract["writes_canonical_packet"])
        self.assertEqual(
            enterprise_response_contract["canonical_packet_not_written"],
            enterprise["canonical_input_packet"],
        )
        self.assertFalse(enterprise_response_contract["promotes_evidence"])
        self.assertFalse(enterprise_response_contract["counts_as_acceptance_gate"])
        self.assertIn(
            "operator supplied validation artifacts for every required modality",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds response packet, candidate packet, and artifact hashes",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds optional assembly manifest hash when emitted",
            enterprise_response_contract["required_controls"],
        )

        production = self._order(report, "production_adapter_paths")
        production_checklist = checklist_by_gate["production_adapter_paths"]
        self.assertEqual(
            production["operator_tasks"]["required_components"],
            production_checklist["required_components"],
        )
        self.assertEqual(
            production["operator_tasks"]["required_artifacts"],
            production_checklist["required_artifacts"],
        )
        self.assertEqual(
            production["operator_tasks"]["required_audit_actions"],
            production_checklist["required_audit_actions"],
        )
        self.assertEqual(
            production["operator_tasks"]["controls"], production_checklist["required_controls"]
        )
        self.assertEqual(
            [row["component_id"] for row in production["operator_tasks"]["per_component_rows"]],
            production_checklist["required_components"],
        )
        production_response_contract = production["operator_tasks"]["response_packet_contract"]
        self.assertEqual(
            production_response_contract["response_packet_type"],
            "production_adapter_response_intake_v1",
        )
        self.assertEqual(
            production_response_contract["response_packet_placeholder"],
            work_orders.PRODUCTION_RESPONSE_PACKET_PLACEHOLDER,
        )
        self.assertEqual(
            production_response_contract["work_packet_path"],
            work_orders.PRODUCTION_RESPONSE_INTAKE_WORK_PACKET,
        )
        self.assertEqual(
            production_response_contract["candidate_output_dir"],
            work_orders.PRODUCTION_RESPONSE_INTAKE_OUTPUT_DIR,
        )
        self.assertEqual(
            production_response_contract["assembly_manifest_output"],
            work_orders.PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT,
        )
        self.assertFalse(production_response_contract["writes_canonical_packet"])
        self.assertEqual(
            production_response_contract["canonical_packet_not_written"],
            production["canonical_input_packet"],
        )
        self.assertFalse(production_response_contract["promotes_evidence"])
        self.assertFalse(production_response_contract["counts_as_acceptance_gate"])
        self.assertIn(
            "operator supplied component artifacts for every required adapter",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds response packet, candidate packet, and artifact hashes",
            production_response_contract["required_controls"],
        )

        for gate_id, checklist_row in checklist_by_gate.items():
            order_blob = json.dumps(self._order(report, gate_id), sort_keys=True)
            for key, value in checklist_row.items():
                if key.startswith("required_") or key == "must_not_claim":
                    if isinstance(value, list):
                        for item in value:
                            with self.subTest(gate_id=gate_id, checklist_key=key, item=item):
                                self.assertIn(str(item), order_blob)

    def test_report_hash_binds_work_order_content(self) -> None:
        checklist = work_orders.load_json(work_orders.CHECKLIST_PATH)
        baseline = work_orders.build_report(checklist_override=checklist)
        mutated = deepcopy(checklist)
        fair = next(
            row
            for row in mutated["remaining_gates"]
            if row["gate_id"] == "fair_external_baseline_comparison"
        )
        fair["required_source_ids_by_baseline"]["hipporag"] = ["hipporag_paper", "hipporag_repo"]

        changed = work_orders.build_report(checklist_override=mutated)

        self.assertNotEqual(baseline["work_orders"], changed["work_orders"])
        self.assertNotEqual(baseline["report_sha256"], changed["report_sha256"])

    def test_commands_validate_intake_candidate_manifests_and_keep_scaffolds_non_evidence(
        self,
    ) -> None:
        report = work_orders.build_report()

        for row in report["work_orders"]:
            with self.subTest(gate_id=row["gate_id"]):
                commands = row["commands"]
                self.assertTrue(commands["assembly_manifest_path"].startswith("work_orders/"))
                self.assertNotIn(row["real_artifact_root"], commands["assembly_manifest_path"])
                self.assertEqual(
                    commands["candidate_manifest_path"],
                    work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS[row["gate_id"]],
                )
                self.assertTrue(commands["candidate_manifest_path"].startswith("work_packets/"))
                self.assertTrue(
                    commands["candidate_manifest_path"].endswith("_candidate_manifest.json")
                )
                self.assertNotIn(row["real_artifact_root"], commands["candidate_manifest_path"])
                self.assertIn(row["assembler_module"], commands["validate_candidate_packet"])
                self.assertIn(
                    commands["candidate_manifest_path"], commands["validate_candidate_packet"]
                )
                self.assertNotIn(
                    commands["assembly_manifest_path"], commands["validate_candidate_packet"]
                )
                self.assertIn("--validate", commands["validate_candidate_packet"])
                self.assertNotIn("--promote", commands["validate_candidate_packet"])
                self.assertNotIn("promote_candidate_packet_after_validator_passes", commands)
                self.assertEqual(
                    commands["run_gate_validator_after_manual_packet_review"],
                    f"python3 {row['validator_module']}",
                )
                self.assertEqual(
                    commands["generate_non_evidence_assembly_manifest_scaffold"],
                    f"python3 {work_orders.ASSEMBLY_MANIFEST_GENERATORS[row['gate_id']]} "
                    f"--output work_orders/{row['gate_id']}_assembly_manifest.json",
                )
                self.assertEqual(
                    commands["rerun_total_acceptance"], "python3 kg_total_acceptance_suite.py"
                )
                self.assertEqual(
                    commands["rerun_objective_audit"], "python3 kg_objective_completion_audit.py"
                )
                self.assertEqual(commands["rerun_preflight"], "python3 real_evidence_preflight.py")
                for command in commands.values():
                    if not isinstance(command, str):
                        continue
                    self.assertNotIn("--promote", command)
                    self.assertNotIn(" cp ", f" {command} ")
                    self.assertNotIn(" mv ", f" {command} ")
                    self.assertNotIn("> inputs/", command)
                    self.assertNotIn(">> inputs/", command)

    def test_missing_response_intake_manifest_mapping_fails_closed(self) -> None:
        report = work_orders.build_report()
        fair = self._order(report, "fair_external_baseline_comparison")
        mapping = dict(work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS)
        mapping.pop("fair_external_baseline_comparison")
        original = work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS

        try:
            work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS = mapping
            with self.assertRaises(KeyError):
                work_orders._common_commands(
                    fair,
                    preflight.EXPECTED_GATES["fair_external_baseline_comparison"],
                )
        finally:
            work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS = original

    def test_fair_work_order_includes_candidate_only_response_intake_command(self) -> None:
        report = work_orders.build_report()
        fair = self._order(report, "fair_external_baseline_comparison")

        command = fair["commands"]["seal_fair_baseline_responses_into_candidate_artifacts"]

        self.assertIn("python3 fair_baseline_response_intake.py", command)
        self.assertIn(f"--work-packet {work_orders.FAIR_RESPONSE_INTAKE_WORK_PACKET}", command)
        self.assertIn(
            f"--response-packet {work_orders.FAIR_RESPONSE_PACKET_PLACEHOLDER}",
            command,
        )
        self.assertNotIn("<", command)
        self.assertNotIn(">", command)
        self.assertIn(f"--output-dir {work_orders.FAIR_RESPONSE_INTAKE_OUTPUT_DIR}", command)
        self.assertTrue(
            work_orders.FAIR_RESPONSE_INTAKE_OUTPUT_DIR.startswith(f"{fair['real_artifact_root']}/")
        )
        self.assertNotIn(fair["canonical_input_packet"], command)
        self.assertIn(
            f"--assembly-manifest-output {work_orders.FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT}",
            command,
        )
        self.assertTrue(
            work_orders.FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT.startswith("work_packets/")
        )
        self.assertNotIn(
            fair["real_artifact_root"], work_orders.FAIR_RESPONSE_INTAKE_MANIFEST_OUTPUT
        )
        self.assertNotIn("--promote", command)
        self.assertFalse(fair["work_order_authority"]["accepts_evidence"])
        self.assertFalse(fair["work_order_authority"]["promotes_evidence"])
        self.assertFalse(fair["work_order_authority"]["writes_canonical_packet"])
        self.assertFalse(fair["work_order_authority"]["counts_as_acceptance_gate"])

    def test_human_work_order_includes_candidate_only_response_intake_command(self) -> None:
        report = work_orders.build_report()
        human = self._order(report, "annotation_adjudication_protocol")

        command = human["commands"]["seal_human_responses_into_candidate_artifacts"]

        self.assertIn("python3 human_annotation_response_intake.py", command)
        self.assertIn(f"--work-packet {work_orders.HUMAN_RESPONSE_INTAKE_WORK_PACKET}", command)
        self.assertIn(
            f"--response-packet {work_orders.HUMAN_RESPONSE_PACKET_PLACEHOLDER}",
            command,
        )
        self.assertNotIn("<", command)
        self.assertNotIn(">", command)
        self.assertIn(f"--output-dir {work_orders.HUMAN_RESPONSE_INTAKE_OUTPUT_DIR}", command)
        self.assertTrue(
            work_orders.HUMAN_RESPONSE_INTAKE_OUTPUT_DIR.startswith(
                f"{human['real_artifact_root']}/"
            )
        )
        self.assertNotIn(human["canonical_input_packet"], command)
        self.assertIn(
            f"--assembly-manifest-output {work_orders.HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT}",
            command,
        )
        self.assertTrue(
            work_orders.HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT.startswith("work_packets/")
        )
        self.assertNotIn(
            human["real_artifact_root"], work_orders.HUMAN_RESPONSE_INTAKE_MANIFEST_OUTPUT
        )
        self.assertNotIn("--promote", command)
        self.assertFalse(human["work_order_authority"]["accepts_evidence"])
        self.assertFalse(human["work_order_authority"]["promotes_evidence"])
        self.assertFalse(human["work_order_authority"]["writes_canonical_packet"])
        self.assertFalse(human["work_order_authority"]["counts_as_acceptance_gate"])

    def test_enterprise_work_order_includes_candidate_only_response_intake_command(self) -> None:
        report = work_orders.build_report()
        enterprise = self._order(report, "multimodal_semantic_validation")

        command = enterprise["commands"]["seal_enterprise_responses_into_candidate_artifacts"]

        self.assertIn("python3 enterprise_multimodal_response_intake.py", command)
        self.assertIn(
            f"--work-packet {work_orders.ENTERPRISE_RESPONSE_INTAKE_WORK_PACKET}",
            command,
        )
        self.assertIn(
            f"--response-packet {work_orders.ENTERPRISE_RESPONSE_PACKET_PLACEHOLDER}",
            command,
        )
        self.assertNotIn("<", command)
        self.assertNotIn(">", command)
        self.assertIn(f"--output-dir {work_orders.ENTERPRISE_RESPONSE_INTAKE_OUTPUT_DIR}", command)
        self.assertTrue(
            work_orders.ENTERPRISE_RESPONSE_INTAKE_OUTPUT_DIR.startswith(
                f"{enterprise['real_artifact_root']}/"
            )
        )
        self.assertNotIn(enterprise["canonical_input_packet"], command)
        self.assertIn(
            f"--assembly-manifest-output {work_orders.ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT}",
            command,
        )
        self.assertTrue(
            work_orders.ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT.startswith("work_packets/")
        )
        self.assertNotIn(
            enterprise["real_artifact_root"],
            work_orders.ENTERPRISE_RESPONSE_INTAKE_MANIFEST_OUTPUT,
        )
        self.assertNotIn("--promote", command)
        self.assertFalse(enterprise["work_order_authority"]["accepts_evidence"])
        self.assertFalse(enterprise["work_order_authority"]["promotes_evidence"])
        self.assertFalse(enterprise["work_order_authority"]["writes_canonical_packet"])
        self.assertFalse(enterprise["work_order_authority"]["counts_as_acceptance_gate"])

    def test_production_work_order_includes_candidate_only_response_intake_command(self) -> None:
        report = work_orders.build_report()
        production = self._order(report, "production_adapter_paths")

        command = production["commands"][
            "seal_production_adapter_responses_into_candidate_artifacts"
        ]

        self.assertIn("python3 production_adapter_response_intake.py", command)
        self.assertIn(
            f"--work-packet {work_orders.PRODUCTION_RESPONSE_INTAKE_WORK_PACKET}",
            command,
        )
        self.assertIn(
            f"--response-packet {work_orders.PRODUCTION_RESPONSE_PACKET_PLACEHOLDER}",
            command,
        )
        self.assertNotIn("<", command)
        self.assertNotIn(">", command)
        self.assertIn(f"--output-dir {work_orders.PRODUCTION_RESPONSE_INTAKE_OUTPUT_DIR}", command)
        self.assertTrue(
            work_orders.PRODUCTION_RESPONSE_INTAKE_OUTPUT_DIR.startswith(
                f"{production['real_artifact_root']}/"
            )
        )
        self.assertNotIn(production["canonical_input_packet"], command)
        self.assertIn(
            f"--assembly-manifest-output {work_orders.PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT}",
            command,
        )
        self.assertTrue(
            work_orders.PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT.startswith("work_packets/")
        )
        self.assertNotIn(
            production["real_artifact_root"],
            work_orders.PRODUCTION_RESPONSE_INTAKE_MANIFEST_OUTPUT,
        )
        self.assertNotIn("--promote", command)
        self.assertFalse(production["work_order_authority"]["accepts_evidence"])
        self.assertFalse(production["work_order_authority"]["promotes_evidence"])
        self.assertFalse(production["work_order_authority"]["writes_canonical_packet"])
        self.assertFalse(production["work_order_authority"]["counts_as_acceptance_gate"])

    def test_cli_does_not_accept_evidence_or_promotion_arguments(self) -> None:
        before = work_orders.OUTPUT_PATH.read_bytes() if work_orders.OUTPUT_PATH.exists() else None
        protected_paths = [
            *self.canonical_packet_paths,
            *self.template_paths,
        ]
        protected_before = snapshot_files(protected_paths)
        roots_before = {
            gate_id: sorted(
                path.relative_to(work_orders.ROOT) for path in gate["real_root"].rglob("*")
            )
            for gate_id, gate in preflight.EXPECTED_GATES.items()
        }
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                work_orders.main(["--promote", "--evidence", "fake"])

        roots_after = {
            gate_id: sorted(
                path.relative_to(work_orders.ROOT) for path in gate["real_root"].rglob("*")
            )
            for gate_id, gate in preflight.EXPECTED_GATES.items()
        }
        self.assertNotEqual(raised.exception.code, 0)
        if before is None:
            self.assertFalse(work_orders.OUTPUT_PATH.exists())
        else:
            self.assertEqual(work_orders.OUTPUT_PATH.read_bytes(), before)
        self.assertEqual(snapshot_files(protected_paths), protected_before)
        self.assertEqual(roots_after, roots_before)

    def test_safety_invariants_reject_templates_fixtures_raw_paths_and_overclaims(self) -> None:
        report = work_orders.build_report()

        for row in report["work_orders"]:
            safety = row["safety"]
            self.assertEqual(
                safety["canonical_packet_must_be_created_only_by_assembler"],
                row["canonical_input_packet"],
            )
            self.assertEqual(safety["real_artifacts_must_live_under"], row["real_artifact_root"])
            self.assertTrue(safety["assembly_manifest_must_not_live_under_real_artifact_root"])
            self.assertIn("templates/", safety["forbidden_sources"])
            self.assertIn("inputs/test_*", safety["forbidden_sources"])
            self.assertIn("results/", safety["forbidden_sources"])
            self.assertIn("raw filesystem paths", safety["forbidden_sources"])
            self.assertEqual(
                safety["operator_must_not_claim"],
                work_orders.load_json(work_orders.CHECKLIST_PATH)["remaining_gates"][
                    report["summary"]["work_order_gate_ids"].index(row["gate_id"])
                ]["must_not_claim"],
            )
        self.assertIn(
            "Do not claim production readiness, top-tier validation, or completed human work from work orders.",
            report["global_safety_invariants"],
        )
        for row in report["work_orders"]:
            order_blob = json.dumps(row, sort_keys=True)
            self.assertNotIn("template_path", row)
            self.assertNotIn("inputs/test_", order_blob.replace('"inputs/test_*"', ""))
            self.assertNotIn("assembler_test", order_blob)
            self.assertNotIn("object://", order_blob)

    def test_main_writes_only_results_work_order_file(self) -> None:
        protected_paths = [
            work_orders.RESULTS / "kg_total_acceptance_snapshot.json",
            work_orders.RESULTS / "kg_objective_completion_audit.json",
            work_orders.RESULTS / "real_evidence_preflight.json",
            work_orders.CHECKLIST_PATH,
            *self.canonical_packet_paths,
            *self.template_paths,
        ]
        protected_before = snapshot_files(protected_paths)
        work_orders_dir_before = snapshot_tree(work_orders.ROOT / "work_orders")
        work_packets_dir_before = snapshot_tree(work_orders.ROOT / "work_packets")
        roots_before = {
            gate_id: sorted(
                path.relative_to(work_orders.ROOT) for path in gate["real_root"].rglob("*")
            )
            for gate_id, gate in preflight.EXPECTED_GATES.items()
        }
        with redirect_stdout(StringIO()):
            work_orders.main()
        output = load_json(work_orders.OUTPUT_PATH)
        roots_after = {
            gate_id: sorted(
                path.relative_to(work_orders.ROOT) for path in gate["real_root"].rglob("*")
            )
            for gate_id, gate in preflight.EXPECTED_GATES.items()
        }

        self.assertEqual(output["artifact_id"], "kg_real_evidence_collection_work_orders_v1")
        self.assertEqual(roots_after, roots_before)
        self.assertEqual(snapshot_files(protected_paths), protected_before)
        self.assertEqual(snapshot_tree(work_orders.ROOT / "work_orders"), work_orders_dir_before)
        self.assertEqual(snapshot_tree(work_orders.ROOT / "work_packets"), work_packets_dir_before)
        self.assertNotEqual(work_orders.OUTPUT_PATH.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
