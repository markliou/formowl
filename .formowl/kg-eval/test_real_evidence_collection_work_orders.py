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


BLOCKED_GATE_IDS = [
    "fair_external_baseline_comparison",
    "annotation_adjudication_protocol",
    "multimodal_semantic_validation",
    "production_adapter_paths",
]


def _base_remaining_gate_row(gate_id: str) -> dict:
    gate = preflight.EXPECTED_GATES[gate_id]
    expected_artifact_id = gate["expected_artifact_ids"][0]
    expected_evidence_kind = gate["expected_evidence_kinds"][0]
    row = {
        "gate_id": gate_id,
        "requirement_id": gate["requirement_id"],
        "input_packet": gate["input_packet_rel"],
        "required_packet_artifact_id": expected_artifact_id,
        "required_evidence_kind": expected_evidence_kind,
        "validator_module": gate["validator_module"],
        "current_blockers": ["missing_operator_response"],
        "must_not_claim": [
            "production readiness",
            "top-tier scientific validation",
            "raw asset access",
            "canonical writes",
        ],
    }
    if gate_id == "multimodal_semantic_validation":
        row.update(
            {
                "required_modalities": [
                    "spreadsheet",
                    "mail",
                    "meeting_audio",
                    "video_ocr",
                ],
                "required_artifacts": [
                    "pilot_manifest",
                    "validation_rows",
                    "llm_subagent_adjudication",
                    "business_decision_review",
                    "permission_probe",
                ],
                "required_controls": [
                    "cross-modal permission probe",
                    "business decision review",
                    "four-specialist LLM subagent panel",
                ],
            }
        )
    if gate_id == "production_adapter_paths":
        row.update(
            {
                "required_components": [
                    "postgres_metadata_store",
                    "pgvector_index",
                    "rapidfuzz_candidate_adapter",
                    "splink_candidate_adapter",
                    "retrieval_gateway",
                    "semantic_gateway",
                    "wiki_projection_adapter",
                ],
                "required_artifacts": [
                    "deployment_manifest",
                    "component_artifacts",
                    "false_merge_labels",
                    "audit_trail",
                    "permission_probe",
                    "rollback_smoke",
                ],
                "required_audit_actions": [
                    "entity_match_without_grant",
                    "raw_asset_read_denied",
                    "canonical_write_guard",
                ],
                "required_controls": [
                    "candidate-only adapters",
                    "permission probes",
                    "rollback smoke",
                    "four-specialist LLM subagent panel",
                ],
            }
        )
    return row


def blocked_checklist(gate_ids: list[str] | None = None) -> dict:
    if gate_ids is None:
        gate_ids = BLOCKED_GATE_IDS
    return {
        "artifact_id": "kg_remaining_evidence_checklist_v1",
        "overall_passed": False,
        "passed_gate_count": 12 - len(gate_ids),
        "failed_gate_count": len(gate_ids),
        "remaining_gates": [_base_remaining_gate_row(gate_id) for gate_id in gate_ids],
        "gate_status_sha256": "test-blocked-gate-status",
        "objective_audit_sha256": "test-blocked-objective-audit",
        "source_snapshot": "results/kg_total_acceptance_snapshot.json",
        "source_objective_audit": "results/kg_objective_completion_audit.json",
    }


def blocked_preflight(gate_ids: list[str] | None = None) -> dict:
    if gate_ids is None:
        gate_ids = BLOCKED_GATE_IDS
    blocked = set(gate_ids)
    report = deepcopy(preflight.build_report())
    report["preflight_state"] = "blocked"
    report["summary"]["blocked_gate_ids"] = list(gate_ids)
    report["summary"]["blocked_gate_count"] = len(gate_ids)
    report["summary"]["total_acceptance_state"] = "blocked"
    report["summary"]["total_acceptance_failed_gate_ids"] = list(gate_ids)
    report["summary"]["gate_status_sha256"] = "test-blocked-gate-status"
    report["checklist_sync"]["status"] = "synchronized"
    report["checklist_sync"]["current_expected_gate_ids"] = list(gate_ids)
    for row in report["gates"]:
        if row["gate_id"] not in blocked:
            continue
        row["current_total_gate_state"] = "blocked"
        row["current_total_gate_blockers"] = ["missing_operator_response"]
        row["validator_status"] = "blocked"
        row["validator_blockers"] = ["missing_operator_response"]
        row["collection_state"] = "missing_real_artifacts_and_packet"
        row["packet_surface"].update(
            {
                "present": False,
                "sha256": None,
                "packet_state": "missing",
                "partial_packet": False,
                "artifact_references": {
                    "reference_count": 0,
                    "real_root_artifact_count": 0,
                    "rejected_reference_count": 0,
                    "rejected_statuses": [],
                    "all_references_under_real_root": False,
                    "references": [],
                },
            }
        )
        row["real_root_scan"] = {
            "root_exists": True,
            "root_ready": False,
            "file_count": 0,
            "candidate_artifact_count": 0,
            "symlink_count": 0,
            "disappeared_file_count": 0,
            "test_or_sandbox_file_count": 0,
            "template_marker_file_count": 0,
            "placeholder_marker_file_count": 0,
            "raw_internal_marker_file_count": 0,
            "candidate_artifact_paths": [],
            "disappeared_file_paths": [],
        }
    return report


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

    def _blocked_report(self, gate_ids: list[str] | None = None) -> dict:
        return work_orders.build_report(
            checklist_override=blocked_checklist(gate_ids),
            preflight_report_override=blocked_preflight(gate_ids),
        )

    def test_work_orders_cover_exact_remaining_gates_and_are_non_authoritative(self) -> None:
        report = self._blocked_report()

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
        self.assertEqual(report["workspace"], ".formowl/kg-eval")
        self.assertFalse(Path(report["workspace"]).is_absolute())
        keys = nested_keys(report)
        strings = nested_strings(report)
        root_text = str(work_orders.ROOT)
        self.assertFalse(
            any(value == root_text or value.startswith(f"{root_text}/") for value in strings)
        )
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
            BLOCKED_GATE_IDS,
        )
        self.assertEqual(
            report["summary"]["work_order_gate_ids"],
            report["summary"]["preflight_blocked_gate_ids"],
        )
        self.assertEqual(report["sync"]["status"], "synchronized")
        self.assertFalse(report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(
            report["sync"]["historical_monitored_gate_ids"],
            [
                "fair_external_baseline_comparison",
                "annotation_adjudication_protocol",
                "multimodal_semantic_validation",
                "production_adapter_paths",
            ],
        )
        self.assertEqual(
            report["sync"]["current_expected_gate_ids"],
            report["summary"]["preflight_blocked_gate_ids"],
        )

    def test_work_orders_stay_synchronized_with_checklist_and_preflight(self) -> None:
        checklist = blocked_checklist()
        preflight_report = blocked_preflight()
        preflight_by_gate = {row["gate_id"]: row for row in preflight_report["gates"]}
        report = work_orders.build_report(
            checklist_override=checklist,
            preflight_report_override=preflight_report,
        )

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

    def test_current_baseline_has_remaining_work_orders_for_all_blocked_gates(self) -> None:
        report = work_orders.build_report()

        self.assertEqual(
            report["work_order_state"], "collection_blocked_until_real_evidence_exists"
        )
        self.assertEqual(report["summary"]["work_order_count"], 4)
        self.assertEqual(report["summary"]["work_order_gate_ids"], BLOCKED_GATE_IDS)
        self.assertEqual(report["summary"]["preflight_blocked_gate_ids"], BLOCKED_GATE_IDS)
        self.assertEqual(report["sync"]["status"], "synchronized")
        self.assertFalse(report["sync"]["normal_work_orders_withheld"])
        self.assertEqual([row["gate_id"] for row in report["work_orders"]], BLOCKED_GATE_IDS)

    def test_blocked_fixture_visibly_remains_missing_real_evidence(self) -> None:
        report = self._blocked_report()

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
        checklist = blocked_checklist()
        drifted_checklist = deepcopy(checklist)
        drifted_checklist["remaining_gates"] = drifted_checklist["remaining_gates"][:-1]

        checklist_report = work_orders.build_report(
            checklist_override=drifted_checklist,
            preflight_report_override=blocked_preflight(),
        )

        self.assertEqual(checklist_report["sync"]["status"], "drifted")
        self.assertTrue(checklist_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(
            checklist_report["work_order_state"],
            "withheld_due_to_checklist_or_preflight_drift",
        )
        self.assertEqual(checklist_report["summary"]["work_order_count"], 0)
        self.assertEqual(checklist_report["work_orders"], [])

        drifted_preflight = blocked_preflight()
        drifted_preflight["checklist_sync"]["status"] = "drifted"

        preflight_report = work_orders.build_report(
            checklist_override=checklist,
            preflight_report_override=drifted_preflight,
        )

        self.assertEqual(preflight_report["sync"]["status"], "drifted")
        self.assertTrue(preflight_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(preflight_report["summary"]["work_order_count"], 0)
        self.assertEqual(preflight_report["work_orders"], [])

    def test_missing_or_malformed_preflight_gate_rows_fail_closed(self) -> None:
        missing_gate = blocked_preflight()
        missing_gate["gates"] = missing_gate["gates"][:-1]

        missing_report = work_orders.build_report(
            checklist_override=blocked_checklist(),
            preflight_report_override=missing_gate,
        )

        self.assertEqual(missing_report["sync"]["status"], "drifted")
        self.assertFalse(missing_report["sync"]["per_gate_preflight_contract_valid"])
        self.assertTrue(missing_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(missing_report["work_orders"], [])

        malformed_gate = blocked_preflight()
        malformed_gate["gates"][0].pop("packet_surface")
        malformed_gate["gates"][2]["real_root_scan"] = {
            "file_count": 0,
            "candidate_artifact_count": 0,
            "disappeared_file_count": "0",
            "root_ready": False,
        }
        malformed_gate["gates"][3]["real_root_scan"].pop("disappeared_file_count")

        malformed_report = work_orders.build_report(
            checklist_override=blocked_checklist(),
            preflight_report_override=malformed_gate,
        )

        self.assertEqual(malformed_report["sync"]["status"], "drifted")
        self.assertFalse(malformed_report["sync"]["per_gate_preflight_contract_valid"])
        details = malformed_report["sync"]["per_gate_preflight_contract"]["details"]
        self.assertFalse(
            details["multimodal_semantic_validation"]["checks"][
                "real_root_disappeared_file_count_is_int"
            ]
        )
        self.assertFalse(
            details["production_adapter_paths"]["checks"]["real_root_disappeared_file_count_is_int"]
        )
        self.assertTrue(malformed_report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(malformed_report["work_orders"], [])

    def test_disappeared_real_root_files_fail_closed_instead_of_collecting(self) -> None:
        unstable_preflight = blocked_preflight()
        unstable_row = next(
            row
            for row in unstable_preflight["gates"]
            if row["gate_id"] == "multimodal_semantic_validation"
        )
        unstable_scan = unstable_row["real_root_scan"]
        unstable_scan["disappeared_file_count"] = 1
        unstable_scan["disappeared_file_paths"] = [
            "inputs/enterprise_multimodal_real/operator-run/transient.json"
        ]

        report = work_orders.build_report(
            checklist_override=blocked_checklist(),
            preflight_report_override=unstable_preflight,
        )
        checks = report["sync"]["per_gate_preflight_contract"]["details"][
            "multimodal_semantic_validation"
        ]["checks"]

        self.assertEqual(report["sync"]["status"], "drifted")
        self.assertFalse(report["sync"]["per_gate_preflight_contract_valid"])
        self.assertFalse(checks["current_absence_visible"])
        self.assertTrue(checks["real_root_disappeared_file_count_is_int"])
        self.assertTrue(report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(report["summary"]["work_order_count"], 0)
        self.assertEqual(report["work_orders"], [])

    def test_clear_preflight_gate_rows_fail_closed_instead_of_collecting(self) -> None:
        clear_preflight = blocked_preflight()
        for gate in clear_preflight["gates"]:
            gate["collection_state"] = "clear"
            gate["current_total_gate_state"] = "clear"
            gate["validator_status"] = "clear"
            gate["packet_surface"]["packet_state"] = "complete"
            gate["real_root_scan"]["root_ready"] = True
            gate["real_root_scan"]["file_count"] = 1
            gate["real_root_scan"]["candidate_artifact_count"] = 1

        report = work_orders.build_report(
            checklist_override=blocked_checklist(),
            preflight_report_override=clear_preflight,
        )

        self.assertEqual(report["sync"]["status"], "drifted")
        self.assertFalse(report["sync"]["per_gate_preflight_contract_valid"])
        self.assertTrue(report["sync"]["normal_work_orders_withheld"])
        self.assertEqual(report["summary"]["work_order_count"], 0)
        self.assertEqual(report["work_orders"], [])

    def test_mocked_clear_validator_states_do_not_become_acceptance_claims(self) -> None:
        mocked_preflight = blocked_preflight()
        for gate in mocked_preflight["gates"]:
            gate["collection_state"] = "passed"
            gate["current_total_gate_state"] = "passed"
            gate["validator_status"] = "passed"
            gate["packet_surface"]["packet_state"] = "passed"
            gate["real_root_scan"]["root_ready"] = True
            gate["real_root_scan"]["file_count"] = 3
            gate["real_root_scan"]["candidate_artifact_count"] = 3
        mocked_preflight["summary"]["total_acceptance_state"] = "passed"

        report = work_orders.build_report(
            checklist_override=blocked_checklist(),
            preflight_report_override=mocked_preflight,
        )

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
        checklist = blocked_checklist()
        checklist_by_gate = {row["gate_id"]: row for row in checklist["remaining_gates"]}
        report = work_orders.build_report(
            checklist_override=checklist,
            preflight_report_override=blocked_preflight(),
        )

        self.assertEqual(report["summary"]["work_order_gate_ids"], BLOCKED_GATE_IDS)
        self.assertIn("fair_external_baseline_comparison", report["summary"]["work_order_gate_ids"])
        self.assertIn("annotation_adjudication_protocol", report["summary"]["work_order_gate_ids"])

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
            "operator_run_id matches the candidate output directory final segment",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "candidate output dir is exactly "
            "inputs/enterprise_multimodal_real/<operator_run_id> outside tests",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "response packet top-level fields and validation wrapper fields are allowlisted",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "raw/internal field names are rejected throughout response payloads",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "candidate artifact parent directories are preflighted before writes",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "after-open partial output writes are cleaned up",
            enterprise_response_contract["required_controls"],
        )
        self.assertIn(
            "created candidate artifacts and optional candidate manifests are rolled back "
            "when assembly, validation, custody hashing, or custody write raises after writes",
            enterprise_response_contract["required_controls"],
        )
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
            "operator_run_id matches the candidate output directory final segment",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            (
                "candidate output dir is exactly "
                "inputs/production_adapter_real/<operator_run_id> outside tests"
            ),
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "response packet top-level fields and adapter wrapper fields are allowlisted",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "raw/internal field names are rejected throughout response payloads",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "candidate artifact parent directories are preflighted before writes",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "after-open partial output writes are cleaned up",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            (
                "created candidate artifacts and optional candidate manifests are rolled back "
                "when assembly or validation raises after writes"
            ),
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "operator supplied component artifacts for every required adapter",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds response packet, candidate packet, and artifact hashes",
            production_response_contract["required_controls"],
        )
        self.assertIn(
            "intake custody receipt binds optional assembly manifest hash when emitted",
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
        checklist = blocked_checklist()
        baseline = work_orders.build_report(
            checklist_override=checklist,
            preflight_report_override=blocked_preflight(),
        )
        mutated = deepcopy(checklist)
        multimodal = next(
            row
            for row in mutated["remaining_gates"]
            if row["gate_id"] == "multimodal_semantic_validation"
        )
        multimodal["required_artifacts"] = [
            *multimodal["required_artifacts"],
            "additional_operator_custody_artifact",
        ]

        changed = work_orders.build_report(
            checklist_override=mutated,
            preflight_report_override=blocked_preflight(),
        )

        self.assertNotEqual(baseline["work_orders"], changed["work_orders"])
        self.assertNotEqual(baseline["report_sha256"], changed["report_sha256"])

    def test_commands_validate_intake_candidate_manifests_and_keep_scaffolds_non_evidence(
        self,
    ) -> None:
        report = self._blocked_report()

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
        report = self._blocked_report()
        mapping = dict(work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS)
        mapping.pop("multimodal_semantic_validation")
        original = work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS

        try:
            work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS = mapping
            with self.assertRaises(KeyError):
                work_orders._common_commands(
                    self._order(report, "multimodal_semantic_validation"),
                    preflight.EXPECTED_GATES["multimodal_semantic_validation"],
                )
        finally:
            work_orders.RESPONSE_INTAKE_MANIFEST_OUTPUTS = original

    def test_blocked_fixture_includes_fair_and_annotation_work_orders(self) -> None:
        report = self._blocked_report()

        self.assertIn(
            "fair_external_baseline_comparison",
            {row["gate_id"] for row in report["work_orders"]},
        )
        self.assertIn(
            "fair_external_baseline_comparison",
            report["sync"]["historical_monitored_gate_ids"],
        )
        self.assertIn(
            "annotation_adjudication_protocol",
            {row["gate_id"] for row in report["work_orders"]},
        )
        self.assertIn(
            "annotation_adjudication_protocol",
            report["sync"]["historical_monitored_gate_ids"],
        )

    def test_enterprise_work_order_includes_candidate_only_response_intake_command(self) -> None:
        report = self._blocked_report()
        enterprise = self._order(report, "multimodal_semantic_validation")

        command = enterprise["commands"]["seal_enterprise_responses_into_candidate_artifacts"]
        preflight_command = enterprise["commands"]["preflight_enterprise_response_packet"]

        self.assertIn("python3 enterprise_multimodal_response_intake.py", command)
        self.assertEqual(preflight_command, f"{command} --preflight-response")
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
        self.assertNotIn("--promote", preflight_command)
        self.assertFalse(enterprise["work_order_authority"]["accepts_evidence"])
        self.assertFalse(enterprise["work_order_authority"]["promotes_evidence"])
        self.assertFalse(enterprise["work_order_authority"]["writes_canonical_packet"])
        self.assertFalse(enterprise["work_order_authority"]["counts_as_acceptance_gate"])

    def test_production_work_order_includes_candidate_only_response_intake_command(self) -> None:
        report = self._blocked_report()
        production = self._order(report, "production_adapter_paths")

        command = production["commands"][
            "seal_production_adapter_responses_into_candidate_artifacts"
        ]
        preflight_command = production["commands"]["preflight_production_adapter_response_packet"]

        self.assertIn("python3 production_adapter_response_intake.py", command)
        self.assertEqual(preflight_command, f"{command} --preflight-response")
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
        self.assertNotIn("--promote", preflight_command)
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
        checklist = blocked_checklist()
        checklist_by_gate = {row["gate_id"]: row for row in checklist["remaining_gates"]}
        report = work_orders.build_report(
            checklist_override=checklist,
            preflight_report_override=blocked_preflight(),
        )

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
                checklist_by_gate[row["gate_id"]]["must_not_claim"],
            )
        self.assertIn(
            "Do not claim production readiness, top-tier validation, or completed adjudication from work orders.",
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
