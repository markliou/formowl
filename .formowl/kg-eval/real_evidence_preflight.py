#!/usr/bin/env python3
"""Preflight the remaining real-evidence collection state.

This helper is a collection-status report, not an acceptance gate. It does not
accept, assemble, promote, repair, or generate evidence. The four broad-gate
validators and the total acceptance suite remain the only executable evidence
authority.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import enterprise_multimodal_validation_validator as enterprise_multimodal
import fair_external_baseline_run_validator as fair_baseline
import human_annotation_adjudication_validator as human_annotation
import kg_objective_completion_audit as objective_audit
import kg_total_acceptance_suite as total_suite
import production_adapter_path_validator as production_adapter


ROOT = Path(__file__).resolve().parent
INPUTS = ROOT / "inputs"
RESULTS = ROOT / "results"
TEMPLATES = ROOT / "templates"
CHECKLIST_PATH = ROOT / "remaining_evidence_checklist.json"
OUTPUT_PATH = RESULTS / "real_evidence_preflight.json"

TEMPLATE_MARKERS = ("template_only", "do_not_submit_as_evidence")
PLACEHOLDER_MARKERS = ("fill-with-real", "fill-with-", "path-to-real", "todo", "TODO")
RAW_MARKERS = (
    "/tmp/",
    "/home/",
    "/var/",
    "/mnt/",
    "file://",
    "s3://",
    "gs://",
    "object://",
    "nas://",
    "smb://",
    "nfs://",
    "webdav://",
    "minio://",
    "postgres://",
    "postgresql://",
    "postgresql+",
    "jdbc:",
    "redis://",
    "mongodb://",
    "mysql://",
    "mssql://",
)
RAW_SCHEMES = {
    "file",
    "s3",
    "gs",
    "object",
    "nas",
    "smb",
    "nfs",
    "webdav",
    "minio",
    "postgres",
    "postgresql",
    "jdbc",
    "redis",
    "mongodb",
    "mysql",
    "mssql",
}

EXPECTED_GATES = {
    "fair_external_baseline_comparison": {
        "requirement_id": "fair_external_baseline_validation",
        "validator": fair_baseline,
        "validator_module": "fair_external_baseline_run_validator.py",
        "assembler_module": "fair_external_baseline_packet_assembler.py",
        "input_packet": INPUTS / "fair_external_baseline_run_packet.json",
        "input_packet_rel": "inputs/fair_external_baseline_run_packet.json",
        "real_root": INPUTS / "fair_baseline_real",
        "real_root_rel": "inputs/fair_baseline_real",
        "template": TEMPLATES / "fair_external_baseline_run_packet.template.json",
        "template_rel": "templates/fair_external_baseline_run_packet.template.json",
    },
    "annotation_adjudication_protocol": {
        "requirement_id": "human_annotation_adjudication_protocol",
        "validator": human_annotation,
        "validator_module": "human_annotation_adjudication_validator.py",
        "assembler_module": "human_annotation_packet_assembler.py",
        "input_packet": INPUTS / "human_annotation_results_v1.json",
        "input_packet_rel": "inputs/human_annotation_results_v1.json",
        "real_root": INPUTS / "human_annotation_real",
        "real_root_rel": "inputs/human_annotation_real",
        "template": TEMPLATES / "human_annotation_results_v1.template.json",
        "template_rel": "templates/human_annotation_results_v1.template.json",
    },
    "multimodal_semantic_validation": {
        "requirement_id": "multimodal_enterprise_validation",
        "validator": enterprise_multimodal,
        "validator_module": "enterprise_multimodal_validation_validator.py",
        "assembler_module": "enterprise_multimodal_packet_assembler.py",
        "input_packet": INPUTS / "enterprise_multimodal_validation_packet.json",
        "input_packet_rel": "inputs/enterprise_multimodal_validation_packet.json",
        "real_root": INPUTS / "enterprise_multimodal_real",
        "real_root_rel": "inputs/enterprise_multimodal_real",
        "template": TEMPLATES / "enterprise_multimodal_validation_packet.template.json",
        "template_rel": "templates/enterprise_multimodal_validation_packet.template.json",
    },
    "production_adapter_paths": {
        "requirement_id": "production_adapter_gate",
        "validator": production_adapter,
        "validator_module": "production_adapter_path_validator.py",
        "assembler_module": "production_adapter_packet_assembler.py",
        "input_packet": INPUTS / "production_adapter_evidence_packet.json",
        "input_packet_rel": "inputs/production_adapter_evidence_packet.json",
        "real_root": INPUTS / "production_adapter_real",
        "real_root_rel": "inputs/production_adapter_real",
        "template": TEMPLATES / "production_adapter_evidence_packet.template.json",
        "template_rel": "templates/production_adapter_evidence_packet.template.json",
    },
}


def sha256_json(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str | None:
    if path.is_symlink() or not path.exists():
        return None
    try:
        metadata = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode):
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def canonical_packet_path_status(path: Path) -> tuple[str | None, str | None]:
    if path.is_symlink():
        return "symlink_rejected", "canonical input packet is a symlink"
    if not path.exists():
        return None, None
    try:
        metadata = path.stat()
    except OSError as exc:
        return (
            "metadata_unreadable",
            f"canonical input packet metadata unreadable: {exc.__class__.__name__}",
        )
    if not stat.S_ISREG(metadata.st_mode):
        return "non_regular_rejected", "canonical input packet is not a file"
    if metadata.st_nlink > 1:
        return "hardlink_rejected", "canonical input packet hardlink alias not accepted"
    return None, None


def read_json_object_status(path: Path) -> tuple[dict[str, Any], str | None]:
    _, path_error = canonical_packet_path_status(path)
    if path_error is not None or not path.exists():
        return {}, path_error
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, f"canonical input packet JSON malformed: {exc.__class__.__name__}"
    if not isinstance(loaded, dict):
        return {}, "canonical input packet is not a JSON object"
    return loaded, None


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def raw_internal_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    if len(stripped) >= 3 and stripped[1:3] in {":\\", ":/"}:
        return True
    lowered = stripped.lower()
    if lowered.startswith(RAW_MARKERS):
        return True
    if ":" not in lowered:
        return False
    scheme = lowered.split(":", 1)[0]
    base_scheme = scheme.split("+", 1)[0]
    return base_scheme in RAW_SCHEMES


def scan_payload(payload: object) -> dict[str, bool]:
    result = {
        "contains_template_marker": False,
        "contains_placeholder_marker": False,
        "contains_raw_internal_marker": False,
    }

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if isinstance(key, str):
                    if key in TEMPLATE_MARKERS:
                        result["contains_template_marker"] = True
                    if _has_any_marker(key, PLACEHOLDER_MARKERS):
                        result["contains_placeholder_marker"] = True
                    if raw_internal_value(key):
                        result["contains_raw_internal_marker"] = True
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str):
            if value in TEMPLATE_MARKERS:
                result["contains_template_marker"] = True
            if _has_any_marker(value, PLACEHOLDER_MARKERS):
                result["contains_placeholder_marker"] = True
            if raw_internal_value(value):
                result["contains_raw_internal_marker"] = True

    visit(payload)
    return result


def _scan_text(path: Path) -> dict[str, bool]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {
            "contains_template_marker": False,
            "contains_placeholder_marker": False,
            "contains_raw_internal_marker": False,
        }
    result = {
        "contains_template_marker": _has_any_marker(text, TEMPLATE_MARKERS),
        "contains_placeholder_marker": _has_any_marker(text, PLACEHOLDER_MARKERS),
        "contains_raw_internal_marker": _has_any_marker(text, RAW_MARKERS),
    }
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return result
    payload_scan = scan_payload(loaded)
    return {key: result[key] or payload_scan[key] for key in result}


def _is_test_or_sandbox_path(path: Path, *, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(
        part == "assembler_test"
        or part.startswith("test_")
        or part.endswith("_test")
        or part.startswith("preflight_test")
        or part == "validator_fixture"
        for part in parts
    )


def scan_real_root(root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "root_exists": root.exists(),
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
    if not root.exists():
        return report

    for path in sorted(root.rglob("*")):
        rel_path = str(path.relative_to(ROOT))
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            report["disappeared_file_count"] += 1
            report["disappeared_file_paths"].append(rel_path)
            continue
        if stat.S_ISLNK(path_stat.st_mode):
            report["symlink_count"] += 1
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            continue
        try:
            text_scan = _scan_text(path)
        except FileNotFoundError:
            report["disappeared_file_count"] += 1
            report["disappeared_file_paths"].append(rel_path)
            continue
        report["file_count"] += 1
        if _is_test_or_sandbox_path(path, root=root):
            report["test_or_sandbox_file_count"] += 1
        else:
            report["candidate_artifact_paths"].append(rel_path)
            report["candidate_artifact_count"] += 1
        if text_scan["contains_template_marker"]:
            report["template_marker_file_count"] += 1
        if text_scan["contains_placeholder_marker"]:
            report["placeholder_marker_file_count"] += 1
        if text_scan["contains_raw_internal_marker"]:
            report["raw_internal_marker_file_count"] += 1
    report["root_ready"] = (
        report["candidate_artifact_count"] > 0
        and report["symlink_count"] == 0
        and report["disappeared_file_count"] == 0
        and report["test_or_sandbox_file_count"] == 0
        and report["template_marker_file_count"] == 0
        and report["placeholder_marker_file_count"] == 0
        and report["raw_internal_marker_file_count"] == 0
    )
    return report


def scan_test_fixture_inputs() -> dict[str, Any]:
    fixture_roots = [path for path in sorted(INPUTS.glob("test_*")) if path.is_dir()]
    file_count = 0
    symlink_count = 0
    for root in fixture_roots:
        for path in root.rglob("*"):
            if path.is_symlink():
                symlink_count += 1
            elif path.is_file():
                file_count += 1
    return {
        "fixture_root_count": len(fixture_roots),
        "fixture_file_count": file_count,
        "fixture_symlink_count": symlink_count,
        "fixture_roots": [str(path.relative_to(ROOT)) for path in fixture_roots],
    }


def template_rejection_report(
    gate: dict[str, Any], *, skip_validator: bool = False
) -> dict[str, Any]:
    template_path = gate["template"]
    template_payload = load_json(template_path)
    template_rel = (
        str(template_path.relative_to(ROOT)) if template_path.exists() else gate["template_rel"]
    )
    if skip_validator:
        return {
            "template_path": template_rel,
            "template_exists": template_path.exists(),
            "template_contains_non_evidence_markers": all(
                template_payload.get(marker) is True for marker in TEMPLATE_MARKERS
            ),
            "template_outside_canonical_input_path": template_rel != gate["input_packet_rel"],
            "template_validator_status": "skipped_due_to_canonical_packet_path_hazard",
            "template_rejected_by_validator": False,
            "template_validator_blockers": [
                "template validator skipped due to canonical packet path hazard"
            ],
        }
    validator_report = gate["validator"].build_report(template_payload)
    return {
        "template_path": template_rel,
        "template_exists": template_path.exists(),
        "template_contains_non_evidence_markers": all(
            template_payload.get(marker) is True for marker in TEMPLATE_MARKERS
        ),
        "template_outside_canonical_input_path": template_rel != gate["input_packet_rel"],
        "template_validator_status": "clear"
        if validator_report.get("passed") is True
        else "blocked",
        "template_rejected_by_validator": validator_report.get("passed") is not True,
        "template_validator_blockers": validator_report.get("blockers", []),
    }


def safe_validator_report(gate: dict[str, Any], *, skip_validator: bool = False) -> dict[str, Any]:
    packet_path = gate["input_packet"]
    _, packet_error = read_json_object_status(packet_path)
    if packet_error is not None:
        return {
            "passed": False,
            "blockers": [packet_error],
            "metrics": {},
            "validator_error": packet_error,
        }
    if skip_validator:
        message = "validator skipped due to canonical packet path hazard"
        return {
            "passed": False,
            "blockers": [message],
            "metrics": {},
            "validator_error": message,
        }
    try:
        report = gate["validator"].build_report()
    except Exception as exc:  # pragma: no cover - defensive path tested via malformed packets.
        return {
            "passed": False,
            "blockers": ["validator raised exception during preflight"],
            "metrics": {},
            "validator_error": f"{exc.__class__.__name__}: {exc}",
        }
    return (
        report
        if isinstance(report, dict)
        else {"passed": False, "blockers": ["validator returned malformed report"]}
    )


def collect_artifact_refs(payload: object) -> list[str]:
    refs: list[str] = []

    def visit(value: object, key: str | None = None) -> None:
        if isinstance(value, dict):
            for nested_key, nested_value in value.items():
                visit(nested_value, nested_key if isinstance(nested_key, str) else None)
        elif isinstance(value, list):
            for nested_value in value:
                visit(nested_value, key)
        elif (
            isinstance(value, str)
            and key is not None
            and (key == "artifact" or key.endswith("_artifact") or key.endswith("_artifacts"))
            and not key.endswith("_sha256")
        ):
            refs.append(value)

    visit(payload)
    return sorted(set(refs))


def classify_artifact_ref(ref: str, *, real_root: Path) -> dict[str, Any]:
    row: dict[str, Any] = {
        "artifact": ref,
        "status": "unknown",
        "exists": False,
        "sha256": None,
        "content_hazards": {
            "contains_template_marker": False,
            "contains_placeholder_marker": False,
            "contains_raw_internal_marker": False,
        },
    }
    if not isinstance(ref, str) or not ref.strip():
        row["status"] = "invalid_reference"
        return row
    path = Path(ref)
    if ref.endswith(".template.json") or "templates" in path.parts:
        row["status"] = "template_rejected"
        return row
    if (
        raw_internal_value(ref)
        or "://" in ref
        or "\\" in ref
        or any(":" in part for part in path.parts)
        or path.is_absolute()
        or ".." in path.parts
        or "." in path.parts
    ):
        row["status"] = "unsafe_rejected"
        return row
    if path.parts[:1] == ("results",):
        row["status"] = "non_real_result_rejected"
        return row
    if path.parts[:1] != ("inputs",):
        row["status"] = "outside_inputs_rejected"
        return row
    if len(path.parts) >= 2 and path.parts[1].startswith("test_"):
        row["status"] = "fixture_rejected"
        return row
    real_root_rel = real_root.relative_to(ROOT).parts
    if path.parts[: len(real_root_rel)] != real_root_rel:
        row["status"] = "outside_real_root_rejected"
        return row
    candidate = ROOT / path
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            row["status"] = "symlink_rejected"
            return row
    if _is_test_or_sandbox_path(candidate, root=real_root):
        row["status"] = "fixture_rejected"
        return row
    if not candidate.is_file():
        row["status"] = "missing"
        return row
    content_hazards = _scan_text(candidate)
    row["exists"] = True
    row["sha256"] = sha256_file(candidate)
    row["content_hazards"] = content_hazards
    if any(content_hazards.values()):
        row["status"] = "content_hazard_rejected"
    else:
        row["status"] = "real_root_artifact"
    return row


def artifact_reference_report(packet_payload: dict[str, Any], *, real_root: Path) -> dict[str, Any]:
    refs = collect_artifact_refs(packet_payload)
    rows = [classify_artifact_ref(ref, real_root=real_root) for ref in refs]
    rejected = [row for row in rows if row["status"] != "real_root_artifact"]
    return {
        "reference_count": len(rows),
        "real_root_artifact_count": sum(1 for row in rows if row["status"] == "real_root_artifact"),
        "rejected_reference_count": len(rejected),
        "rejected_statuses": sorted({row["status"] for row in rejected}),
        "all_references_under_real_root": bool(rows) and not rejected,
        "references": rows,
    }


def checklist_row_for_gate(gate_id: str) -> dict[str, Any]:
    checklist = load_json(CHECKLIST_PATH)
    for row in checklist.get("remaining_gates", []):
        if row.get("gate_id") == gate_id:
            return row
    return {}


def packet_surface_report(
    gate_id: str, gate: dict[str, Any], validator_report: dict[str, Any]
) -> dict[str, Any]:
    packet_path = gate["input_packet"]
    packet_payload, packet_error = read_json_object_status(packet_path)
    path_state, _ = canonical_packet_path_status(packet_path)
    packet_text_scan = (
        _scan_text(packet_path) if packet_path.exists() and packet_error is None else {}
    )
    checklist_row = checklist_row_for_gate(gate_id)
    expected_artifact_id = checklist_row.get("required_packet_artifact_id")
    expected_evidence_kind = checklist_row.get("required_evidence_kind")
    json_object = packet_error is None and isinstance(packet_payload, dict) and bool(packet_payload)
    packet_has_identity = (
        json_object
        and packet_payload.get("artifact_id") == expected_artifact_id
        and packet_payload.get("evidence_kind") == expected_evidence_kind
    )
    validator_clear = validator_report.get("passed") is True
    if path_state is not None:
        packet_state = path_state
    elif not packet_path.exists():
        packet_state = "missing"
    elif packet_error is not None or not json_object:
        packet_state = "invalid_json_or_non_object"
    elif packet_has_identity and not validator_clear:
        packet_state = "partial"
    elif validator_clear:
        packet_state = "validator_clear"
    else:
        packet_state = "validator_failed"
    artifact_refs = artifact_reference_report(
        packet_payload if json_object else {}, real_root=gate["real_root"]
    )
    return {
        "input_packet": gate["input_packet_rel"],
        "present": packet_path.exists(),
        "sha256": sha256_file(packet_path) if path_state is None else None,
        "json_object": json_object,
        "packet_state": packet_state,
        "packet_error": packet_error,
        "symlink_rejected": packet_path.is_symlink(),
        "hardlink_rejected": packet_state == "hardlink_rejected",
        "non_regular_rejected": packet_state == "non_regular_rejected",
        "partial_packet": packet_state == "partial",
        "has_expected_artifact_id": json_object
        and packet_payload.get("artifact_id") == expected_artifact_id,
        "has_expected_evidence_kind": json_object
        and packet_payload.get("evidence_kind") == expected_evidence_kind,
        "contains_template_marker": bool(packet_text_scan.get("contains_template_marker")),
        "contains_placeholder_marker": bool(packet_text_scan.get("contains_placeholder_marker")),
        "contains_raw_internal_marker": bool(packet_text_scan.get("contains_raw_internal_marker")),
        "artifact_references": artifact_refs,
    }


def collection_state(
    *,
    packet_state: str,
    validator_clear: bool,
    real_root_scan: dict[str, Any],
    artifact_refs: dict[str, Any],
) -> str:
    if packet_state == "missing":
        if real_root_scan["file_count"] > 0:
            return "real_artifacts_present_without_valid_packet"
        return "missing_real_artifacts_and_packet"
    if validator_clear and artifact_refs["all_references_under_real_root"]:
        return "canonical_packet_validator_clear"
    if validator_clear and not artifact_refs["all_references_under_real_root"]:
        return "canonical_packet_validator_clear_but_references_rejected"
    if packet_state == "partial":
        return "partial_canonical_packet"
    if packet_state != "partial":
        return "validator_failed_canonical_packet"
    return "partial_canonical_packet"


def gate_preflight_report(
    gate_id: str,
    checklist_row: dict[str, Any],
    total_gate: dict[str, Any],
    *,
    skip_validators: bool = False,
) -> dict[str, Any]:
    gate = EXPECTED_GATES[gate_id]
    validator_report = safe_validator_report(gate, skip_validator=skip_validators)
    real_root_scan = scan_real_root(gate["real_root"])
    packet_report = packet_surface_report(gate_id, gate, validator_report)
    template_report = template_rejection_report(gate, skip_validator=skip_validators)
    validator_clear = validator_report.get("passed") is True
    return {
        "gate_id": gate_id,
        "requirement_id": checklist_row.get("requirement_id") or gate["requirement_id"],
        "validator_module": gate["validator_module"],
        "assembler_module": gate["assembler_module"],
        "input_packet": gate["input_packet_rel"],
        "real_artifact_root": gate["real_root_rel"],
        "current_total_gate_state": "clear" if total_gate.get("passed") is True else "blocked",
        "current_total_gate_blockers": total_gate.get("blockers", []),
        "validator_status": "clear" if validator_clear else "blocked",
        "validator_blockers": validator_report.get("blockers", []),
        "validator_metrics": validator_report.get("metrics", {}),
        "validator_packet_sha256": validator_report.get("packet_sha256"),
        "collection_state": collection_state(
            packet_state=packet_report["packet_state"],
            validator_clear=validator_clear,
            real_root_scan=real_root_scan,
            artifact_refs=packet_report["artifact_references"],
        ),
        "packet_surface": packet_report,
        "real_root_scan": real_root_scan,
        "template_guard": template_report,
        "checklist_current_blockers": checklist_row.get("current_blockers", []),
        "checklist_required_evidence_kind": checklist_row.get("required_evidence_kind"),
        "checklist_required_packet_artifact_id": checklist_row.get("required_packet_artifact_id"),
        "preflight_authority": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_canonical_packet": False,
            "counts_as_acceptance_gate": False,
        },
    }


def canonical_packet_path_hazards() -> dict[str, dict[str, str]]:
    hazards: dict[str, dict[str, str]] = {}
    for gate_id, gate in EXPECTED_GATES.items():
        packet_state, packet_error = canonical_packet_path_status(gate["input_packet"])
        if packet_state is not None and packet_error is not None:
            hazards[gate_id] = {
                "packet_state": packet_state,
                "packet_error": packet_error,
                "input_packet": gate["input_packet_rel"],
            }
    return hazards


def build_report() -> dict[str, Any]:
    packet_path_hazards = canonical_packet_path_hazards()
    if packet_path_hazards:
        total_report = load_json(RESULTS / "kg_total_acceptance_snapshot.json")
        total_error = "skipped total acceptance refresh due to canonical packet path hazard"
    else:
        try:
            total_report = total_suite.build_report()
            total_error = None
        except Exception as exc:
            total_report = load_json(RESULTS / "kg_total_acceptance_snapshot.json")
            total_error = f"{exc.__class__.__name__}: {exc}"
    if not total_report:
        total_report = {"summary": {"failed_gate_ids": [], "overall_passed": False}, "gates": []}
    if packet_path_hazards:
        audit_report = load_json(RESULTS / "kg_objective_completion_audit.json")
        audit_error = "skipped objective audit refresh due to canonical packet path hazard"
    else:
        try:
            audit_report = objective_audit.build_report()
            audit_error = None
        except Exception as exc:
            audit_report = load_json(RESULTS / "kg_objective_completion_audit.json")
            audit_error = f"{exc.__class__.__name__}: {exc}"
    if not audit_report:
        audit_report = {"audit_sha256": None}
    summary = total_report["summary"]
    total_gates = {gate["gate_id"]: gate for gate in total_report["gates"]}
    checklist = load_json(CHECKLIST_PATH)
    checklist_rows = {row["gate_id"]: row for row in checklist.get("remaining_gates", [])}

    failed_gate_ids = summary.get("failed_gate_ids", [])
    expected_gate_ids = list(EXPECTED_GATES)
    checklist_sync = {
        "checklist_present": bool(checklist),
        "checklist_gate_ids_match_expected": list(checklist_rows) == expected_gate_ids,
        "checklist_failed_gate_ids_match_total": list(checklist_rows) == failed_gate_ids,
        "checklist_counts_match_total": checklist.get("failed_gate_count")
        == summary.get("failed_gate_count")
        and checklist.get("passed_gate_count") == summary.get("passed_gate_count"),
        "checklist_gate_status_sha256_matches_total": checklist.get("gate_status_sha256")
        == summary.get("gate_status_sha256"),
        "checklist_objective_audit_sha256_matches_current": checklist.get("objective_audit_sha256")
        == audit_report.get("audit_sha256"),
        "checklist_source_snapshot_path_matches": checklist.get("source_snapshot")
        == "results/kg_total_acceptance_snapshot.json",
        "checklist_source_objective_audit_path_matches": checklist.get("source_objective_audit")
        == "results/kg_objective_completion_audit.json",
    }
    checklist_sync["status"] = "synchronized" if all(checklist_sync.values()) else "drifted"

    gate_reports = [
        gate_preflight_report(
            gate_id,
            checklist_rows.get(gate_id, {}),
            total_gates.get(gate_id, {}),
            skip_validators=bool(packet_path_hazards),
        )
        for gate_id in expected_gate_ids
    ]
    validator_clear_gate_ids = [
        row["gate_id"] for row in gate_reports if row["validator_status"] == "clear"
    ]
    blocked_gate_ids = [
        row["gate_id"] for row in gate_reports if row["validator_status"] != "clear"
    ]
    template_guard_clear = all(
        row["template_guard"]["template_rejected_by_validator"] for row in gate_reports
    )
    all_validators_clear = len(validator_clear_gate_ids) == len(gate_reports)
    all_collections_canonical = all(
        row["collection_state"] == "canonical_packet_validator_clear" for row in gate_reports
    )
    no_packet_or_artifact_hazards = all(
        not row["packet_surface"]["contains_template_marker"]
        and not row["packet_surface"]["contains_placeholder_marker"]
        and not row["packet_surface"]["contains_raw_internal_marker"]
        and row["real_root_scan"]["symlink_count"] == 0
        and row["real_root_scan"]["disappeared_file_count"] == 0
        and row["real_root_scan"]["test_or_sandbox_file_count"] == 0
        and row["real_root_scan"]["template_marker_file_count"] == 0
        and row["real_root_scan"]["placeholder_marker_file_count"] == 0
        and row["real_root_scan"]["raw_internal_marker_file_count"] == 0
        for row in gate_reports
    )
    preflight_state = (
        "validator_clear_for_all_broad_gates"
        if checklist_sync["status"] == "synchronized"
        and template_guard_clear
        and all_validators_clear
        and all_collections_canonical
        and no_packet_or_artifact_hazards
        else "blocked"
    )

    return {
        "artifact_id": "kg_real_evidence_preflight_v1",
        "workspace": str(ROOT),
        "source_checklist": "remaining_evidence_checklist.json",
        "source_total_acceptance_snapshot": "results/kg_total_acceptance_snapshot.json",
        "source_objective_completion_audit": "results/kg_objective_completion_audit.json",
        "preflight_state": preflight_state,
        "preflight_authority": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_canonical_packets": False,
            "counts_as_acceptance_gate": False,
            "replaces_authoritative_validators": False,
        },
        "canonical_packet_path_hazards": packet_path_hazards,
        "summary": {
            "validator_clear_gate_count": len(validator_clear_gate_ids),
            "validator_clear_gate_ids": validator_clear_gate_ids,
            "blocked_gate_count": len(blocked_gate_ids),
            "blocked_gate_ids": blocked_gate_ids,
            "checklist_sync_status": checklist_sync["status"],
            "template_guard_status": "clear" if template_guard_clear else "blocked",
            "broad_validator_status": "clear" if all_validators_clear else "blocked",
            "canonical_collection_status": "clear" if all_collections_canonical else "blocked",
            "no_packet_or_artifact_hazards": no_packet_or_artifact_hazards,
            "total_acceptance_state": "clear"
            if summary.get("overall_passed") is True
            else "blocked",
            "total_acceptance_failed_gate_ids": failed_gate_ids,
            "gate_status_sha256": summary.get("gate_status_sha256"),
            "total_acceptance_report_error": total_error,
            "objective_audit_report_error": audit_error,
        },
        "checklist_sync": checklist_sync,
        "test_fixture_inputs": scan_test_fixture_inputs(),
        "gates": gate_reports,
        "report_sha256": sha256_json(
            {
                "validator_clear_gate_ids": validator_clear_gate_ids,
                "blocked_gate_ids": blocked_gate_ids,
                "checklist_sync": checklist_sync,
                "gate_status_sha256": summary.get("gate_status_sha256"),
            }
        ),
    }


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    report = build_report()
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
