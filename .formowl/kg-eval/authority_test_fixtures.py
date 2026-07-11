#!/usr/bin/env python3
"""Clone-reproducible filesystem fixtures for KG evaluation authority tests."""

from __future__ import annotations

import json
from copy import deepcopy
import shutil
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import enterprise_multimodal_validation_validator as enterprise_multimodal
import fair_external_baseline_run_validator as fair_baseline
import human_annotation_adjudication_validator as human_annotation
import kg_objective_completion_audit as objective_audit
import kg_total_acceptance_suite as total_suite
import production_adapter_path_validator as production_adapter
import real_evidence_collection_work_orders as work_orders
import real_evidence_gate_progress as gate_progress
import real_evidence_governance_approval as governance_approval
import real_evidence_operator_guide as operator_guide
import real_evidence_preflight as preflight
import real_evidence_response_packet_templates as response_templates
import real_evidence_submission_manifest as submission_manifest


SOURCE_ROOT = Path(__file__).resolve().parent
BLOCKED_SNAPSHOT_ROOT = SOURCE_ROOT / "snapshots" / "current_blocked"
TRACKED_WORK_PACKET_FIXTURES = (
    "enterprise_multimodal_collection_packet_preview.json",
    "enterprise_multimodal_response_packet.template.json",
    "fair_baseline_response_packet.template.json",
    "fair_baseline_run_work_packet_preview.json",
    "human_annotation_response_packet.template.json",
    "human_annotation_work_packet_preview.json",
    "production_adapter_collection_packet_preview.json",
    "production_adapter_response_packet.template.json",
    "remaining_real_evidence_governance_approval.template.json",
    "remaining_real_evidence_operator_guide.md",
    "remaining_real_evidence_submission_manifest.template.json",
)


class AuthorityWorkspace:
    """Isolate authority tests from ignored operator results and real inputs."""

    def __init__(self, state: str = "blocked") -> None:
        if state not in {"blocked", "completed"}:
            raise ValueError(f"unsupported authority fixture state: {state}")
        self.state = state
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="formowl-kg-authority-")
        self.root = Path(self._temporary_directory.name) / "kg-eval"
        self.inputs = self.root / "inputs"
        self.results = self.root / "results"
        self.templates = self.root / "templates"
        self.work_packets = self.root / "work_packets"
        self.checklist = self.root / "remaining_evidence_checklist.json"
        self._stack = ExitStack()

    def __enter__(self) -> AuthorityWorkspace:
        try:
            return self._prepare()
        except BaseException:
            self._stack.close()
            self._temporary_directory.cleanup()
            raise

    def _prepare(self) -> AuthorityWorkspace:
        self.inputs.mkdir(parents=True)
        self.results.mkdir(parents=True)
        self.work_packets.mkdir(parents=True)
        for name in TRACKED_WORK_PACKET_FIXTURES:
            shutil.copy2(SOURCE_ROOT / "work_packets" / name, self.work_packets / name)
        shutil.copytree(SOURCE_ROOT / "templates", self.templates)
        shutil.copy2(SOURCE_ROOT / "remaining_evidence_checklist.json", self.checklist)
        for snapshot in BLOCKED_SNAPSHOT_ROOT.glob("*.json"):
            shutil.copy2(snapshot, self.results / snapshot.name)

        gates = {}
        validators = {
            "fair_external_baseline_comparison": fair_baseline,
            "annotation_adjudication_protocol": human_annotation,
            "multimodal_semantic_validation": enterprise_multimodal,
            "production_adapter_paths": production_adapter,
        }
        for gate_id, source_gate in preflight.EXPECTED_GATES.items():
            gate = dict(source_gate)
            gate["input_packet"] = self.root / gate["input_packet_rel"]
            gate["real_root"] = self.root / gate["real_root_rel"]
            gate["template"] = self.root / gate["template_rel"]
            gate["real_root"].mkdir(parents=True, exist_ok=True)
            gates[gate_id] = gate
            validator = validators[gate_id]
            self._stack.enter_context(mock.patch.object(validator, "ROOT", self.root))
            self._stack.enter_context(mock.patch.object(validator, "INPUTS", self.inputs))
            self._stack.enter_context(
                mock.patch.object(validator, "PACKET_PATH", gate["input_packet"])
            )
            self._stack.enter_context(
                mock.patch.object(validator, "REAL_ARTIFACT_ROOT_PATH", gate["real_root"])
            )

        patches = (
            (preflight, "ROOT", self.root),
            (preflight, "INPUTS", self.inputs),
            (preflight, "RESULTS", self.results),
            (preflight, "TEMPLATES", self.templates),
            (preflight, "CHECKLIST_PATH", self.checklist),
            (preflight, "OUTPUT_PATH", self.results / "real_evidence_preflight.json"),
            (preflight, "EXPECTED_GATES", gates),
            (total_suite, "RESULTS", self.results),
            (objective_audit, "RESULTS", self.results),
            (work_orders, "ROOT", self.root),
            (work_orders, "RESULTS", self.results),
            (work_orders, "CHECKLIST_PATH", self.checklist),
            (
                work_orders,
                "OUTPUT_PATH",
                self.results / "real_evidence_collection_work_orders.json",
            ),
            (gate_progress, "ROOT", self.root),
            (gate_progress, "RESULTS", self.results),
            (gate_progress, "WORK_PACKETS", self.work_packets),
            (gate_progress, "OUTPUT_PATH", self.results / "real_evidence_gate_progress.json"),
            (governance_approval, "ROOT", self.root),
            (governance_approval, "WORK_PACKETS", self.work_packets),
            (submission_manifest, "ROOT", self.root),
            (submission_manifest, "WORK_PACKETS", self.work_packets),
            (operator_guide, "ROOT", self.root),
            (operator_guide, "WORK_PACKETS", self.work_packets),
            (
                operator_guide,
                "DEFAULT_OUTPUT_PATH",
                self.work_packets / "remaining_real_evidence_operator_guide.md",
            ),
            (response_templates, "ROOT", self.root),
            (response_templates, "WORK_PACKETS", self.work_packets),
            (
                response_templates,
                "TEMPLATE_PATHS",
                {
                    gate_id: self.work_packets / path.name
                    for gate_id, path in response_templates.TEMPLATE_PATHS.items()
                },
            ),
        )
        for module, attribute, value in patches:
            self._stack.enter_context(mock.patch.object(module, attribute, value))

        if self.state == "completed":
            self._install_completed_reports()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stack.close()
        self._temporary_directory.cleanup()

    @property
    def canonical_packets(self) -> list[Path]:
        return [gate["input_packet"] for gate in preflight.EXPECTED_GATES.values()]

    def _install_completed_reports(self) -> None:
        completed = json.loads(
            (BLOCKED_SNAPSHOT_ROOT / "kg_total_acceptance_snapshot.json").read_text(
                encoding="utf-8"
            )
        )
        for gate in completed["gates"]:
            gate["passed"] = True
            gate["blockers"] = []
        completed["summary"].update(
            {
                "overall_passed": True,
                "passed_gate_count": len(completed["gates"]),
                "failed_gate_count": 0,
                "failed_gate_ids": [],
            }
        )
        completed["summary"]["gate_status_sha256"] = total_suite.sha256_json(
            {
                "passed": [gate["gate_id"] for gate in completed["gates"]],
                "failed": [],
            }
        )
        (self.results / "kg_total_acceptance_snapshot.json").write_text(
            json.dumps(completed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

        completed_audit = objective_audit.build_report()
        (self.results / "kg_objective_completion_audit.json").write_text(
            json.dumps(completed_audit, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        completed_checklist = json.loads(self.checklist.read_text(encoding="utf-8"))
        completed_checklist.update(
            {
                "overall_passed": True,
                "passed_gate_count": len(completed["gates"]),
                "failed_gate_count": 0,
                "remaining_gates": [],
                "gate_status_sha256": completed["summary"]["gate_status_sha256"],
                "objective_audit_sha256": completed_audit["audit_sha256"],
            }
        )
        self.checklist.write_text(
            json.dumps(completed_checklist, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        completed_preflight = {
            "artifact_id": "kg_real_evidence_preflight_completed_fixture_v1",
            "preflight_state": "validator_clear_for_all_broad_gates",
            "summary": {
                "validator_clear_gate_count": len(preflight.EXPECTED_GATES),
                "validator_clear_gate_ids": list(preflight.EXPECTED_GATES),
                "blocked_gate_count": 0,
                "blocked_gate_ids": [],
                "checklist_sync_status": "synchronized",
                "broad_validator_status": "clear",
                "total_acceptance_state": "clear",
                "total_acceptance_failed_gate_ids": [],
                "gate_status_sha256": completed["summary"]["gate_status_sha256"],
            },
            "checklist_sync": {
                "status": "synchronized",
                "current_expected_gate_ids": [],
                "diagnostics": [],
            },
            "gates": [
                {"gate_id": gate_id, "validator_status": "clear"}
                for gate_id in preflight.EXPECTED_GATES
            ],
        }

        self._stack.enter_context(
            mock.patch.object(total_suite, "build_report", side_effect=lambda: deepcopy(completed))
        )
        self._stack.enter_context(
            mock.patch.object(
                objective_audit,
                "build_report",
                side_effect=lambda: deepcopy(completed_audit),
            )
        )
        self._stack.enter_context(
            mock.patch.object(
                preflight,
                "build_report",
                side_effect=lambda: deepcopy(completed_preflight),
            )
        )
