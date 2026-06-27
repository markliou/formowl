#!/usr/bin/env python3
"""Validate operator submission manifests for remaining KG evidence.

This helper checks that operator response-packet paths and candidate-only
intake destinations are safe before running any intake command. It does not
read response packet contents, write candidate artifacts, promote evidence, or
write canonical input packets.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
WORK_PACKETS = ROOT / "work_packets"
DEFAULT_TEMPLATE_OUTPUT = WORK_PACKETS / "remaining_real_evidence_submission_manifest.template.json"
MANIFEST_TYPE = "kg_remaining_real_evidence_submission_manifest_v1"
OPERATOR_RESPONSE_PACKET_FILENAME = "operator_response_packet.json"
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,96}$")
FORBIDDEN_SCHEMES = (
    "file://",
    "s3://",
    "gs://",
    "object://",
    "postgres://",
    "postgresql://",
    "mysql://",
    "sqlite://",
)
FORBIDDEN_PATH_PARTS = {
    "templates",
    "results",
    "scratch",
    "tmp",
    "worker_scratch",
}
CANONICAL_INPUT_PACKETS = {
    "inputs/fair_external_baseline_run_packet.json",
    "inputs/human_annotation_results_v1.json",
    "inputs/enterprise_multimodal_validation_packet.json",
    "inputs/production_adapter_evidence_packet.json",
}
TOP_LEVEL_ALLOWED_FIELDS = {
    "manifest_type",
    "submissions",
    "claim_boundary",
}
SUBMISSION_ALLOWED_FIELDS = {
    "gate_id",
    "response_packet_type",
    "response_packet",
    "operator_run_id",
    "output_dir",
    "assembly_manifest_output",
}


@dataclass(frozen=True)
class ExpectedSubmission:
    gate_id: str
    intake_script: str
    response_packet_type: str
    work_packet_path: str
    response_packet_placeholder: str
    real_root: str
    assembly_manifest_output: str
    canonical_packet: str

    def output_dir_for(self, operator_run_id: str) -> str:
        return f"{self.real_root}/{operator_run_id}"

    def response_packet_for(self, operator_run_id: str) -> str:
        return f"{self.output_dir_for(operator_run_id)}/{OPERATOR_RESPONSE_PACKET_FILENAME}"


EXPECTED_SUBMISSIONS = [
    ExpectedSubmission(
        gate_id="fair_external_baseline_comparison",
        intake_script="fair_baseline_response_intake.py",
        response_packet_type="fair_baseline_response_intake_v1",
        work_packet_path="work_packets/fair_baseline_run_work_packet_preview.json",
        response_packet_placeholder="OPERATOR_FAIR_BASELINE_RESPONSE_PACKET_JSON",
        real_root="inputs/fair_baseline_real",
        assembly_manifest_output=(
            "work_packets/fair_external_baseline_comparison_candidate_manifest.json"
        ),
        canonical_packet="inputs/fair_external_baseline_run_packet.json",
    ),
    ExpectedSubmission(
        gate_id="annotation_adjudication_protocol",
        intake_script="human_annotation_response_intake.py",
        response_packet_type="human_annotation_response_intake_v1",
        work_packet_path="work_packets/human_annotation_work_packet_preview.json",
        response_packet_placeholder="OPERATOR_RESPONSE_PACKET_JSON",
        real_root="inputs/human_annotation_real",
        assembly_manifest_output=(
            "work_packets/annotation_adjudication_protocol_candidate_manifest.json"
        ),
        canonical_packet="inputs/human_annotation_results_v1.json",
    ),
    ExpectedSubmission(
        gate_id="multimodal_semantic_validation",
        intake_script="enterprise_multimodal_response_intake.py",
        response_packet_type="enterprise_multimodal_response_intake_v1",
        work_packet_path="work_packets/enterprise_multimodal_collection_packet_preview.json",
        response_packet_placeholder="OPERATOR_ENTERPRISE_RESPONSE_PACKET_JSON",
        real_root="inputs/enterprise_multimodal_real",
        assembly_manifest_output=(
            "work_packets/multimodal_semantic_validation_candidate_manifest.json"
        ),
        canonical_packet="inputs/enterprise_multimodal_validation_packet.json",
    ),
    ExpectedSubmission(
        gate_id="production_adapter_paths",
        intake_script="production_adapter_response_intake.py",
        response_packet_type="production_adapter_response_intake_v1",
        work_packet_path="work_packets/production_adapter_collection_packet_preview.json",
        response_packet_placeholder="OPERATOR_PRODUCTION_ADAPTER_RESPONSE_PACKET_JSON",
        real_root="inputs/production_adapter_real",
        assembly_manifest_output="work_packets/production_adapter_paths_candidate_manifest.json",
        canonical_packet="inputs/production_adapter_evidence_packet.json",
    ),
]
EXPECTED_BY_GATE = {row.gate_id: row for row in EXPECTED_SUBMISSIONS}


class ManifestError(ValueError):
    """Raised when a submission manifest is malformed."""


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def load_json_file(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ManifestError("submission manifest JSON must be an object")
    return loaded


def build_template() -> dict[str, Any]:
    return {
        "manifest_type": MANIFEST_TYPE,
        "template_only": True,
        "do_not_submit_as_evidence": True,
        "claim_boundary": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_candidate_artifacts": False,
            "writes_canonical_packets": False,
            "counts_as_acceptance_gate": False,
        },
        "submissions": [
            {
                "gate_id": expected.gate_id,
                "response_packet_type": expected.response_packet_type,
                "response_packet": expected.response_packet_for("OPERATOR_RUN_ID"),
                "operator_run_id": "OPERATOR_RUN_ID",
                "output_dir": f"{expected.real_root}/OPERATOR_RUN_ID",
                "assembly_manifest_output": expected.assembly_manifest_output,
            }
            for expected in EXPECTED_SUBMISSIONS
        ],
    }


def _forbidden_marker(value: str) -> bool:
    lowered = value.lower()
    return (
        value.startswith(("/", "\\"))
        or "\\" in value
        or any(scheme in lowered for scheme in FORBIDDEN_SCHEMES)
        or lowered.startswith("~")
    )


def _path_parts_are_test_or_template(parts: tuple[str, ...]) -> bool:
    return any(
        part in FORBIDDEN_PATH_PARTS
        or part == "templates"
        or part.endswith(".template.json")
        or part.startswith("test_")
        or part.endswith("_test")
        or part.startswith("preflight_test")
        or part == "validator_fixture"
        or part == "assembler_test"
        or part == "sandbox"
        or part.startswith("sandbox_")
        or part.endswith("_sandbox")
        for part in parts
    )


def _safe_relative_path(value: object, field_name: str) -> tuple[Path | None, list[str]]:
    blockers: list[str] = []
    if not isinstance(value, str) or not value.strip():
        return None, [f"{field_name} must be a non-empty string"]
    if _forbidden_marker(value):
        blockers.append(f"{field_name} must be a safe repo-relative path")
    path = Path(value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        blockers.append(f"{field_name} must not be absolute or use dot segments")
    if not path.parts:
        blockers.append(f"{field_name} must include a path")
    if _path_parts_are_test_or_template(path.parts):
        blockers.append(f"{field_name} must not use templates, results, test, or sandbox paths")
    rel = str(path)
    if rel in CANONICAL_INPUT_PACKETS:
        blockers.append(f"{field_name} must not target canonical input packets")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        blockers.append(f"{field_name} escapes the KG-eval workspace")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            blockers.append(f"{field_name} symlink components are not accepted")
            break
    return path, blockers


def _safe_work_packets_path(value: object, field_name: str) -> tuple[Path | None, list[str]]:
    path, blockers = _safe_relative_path(value, field_name)
    if path is None:
        return None, blockers
    if not path.parts or path.parts[0] != "work_packets":
        blockers.append(f"{field_name} must live under work_packets/")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_PACKETS.resolve())
    except ValueError:
        blockers.append(f"{field_name} escapes work_packets/")
    return path, blockers


def _safe_identifier(value: object, field_name: str) -> tuple[str | None, list[str]]:
    if not isinstance(value, str) or not value.strip():
        return None, [f"{field_name} must be a non-empty string"]
    blockers: list[str] = []
    if not SAFE_ID_RE.match(value):
        blockers.append(f"{field_name} must be a safe identifier")
    lowered = value.lower()
    if any(marker in lowered for marker in ("test_", "fixture", "template", "sandbox")):
        blockers.append(f"{field_name} must not use test, fixture, template, or sandbox markers")
    return value, blockers


def _validate_claim_boundary(payload: dict[str, Any], blockers: list[str]) -> None:
    boundary = payload.get("claim_boundary")
    if not isinstance(boundary, dict):
        blockers.append("claim_boundary must be present and must be an object")
        return
    expected = {
        "accepts_evidence": False,
        "promotes_evidence": False,
        "writes_candidate_artifacts": False,
        "writes_canonical_packets": False,
        "counts_as_acceptance_gate": False,
    }
    if set(boundary) != set(expected):
        blockers.append("claim_boundary fields must exactly match the non-authoritative contract")
        return
    for key, expected_value in expected.items():
        if boundary.get(key) is not expected_value:
            blockers.append(f"claim_boundary.{key} must be {expected_value}")


def _validate_submission(
    submission: object,
    expected: ExpectedSubmission,
    *,
    require_existing_response_packets: bool,
) -> tuple[dict[str, Any] | None, list[str]]:
    blockers: list[str] = []
    if not isinstance(submission, dict):
        return None, [f"{expected.gate_id}: submission must be an object"]

    unsupported = sorted(set(submission) - SUBMISSION_ALLOWED_FIELDS)
    if unsupported:
        blockers.append(
            f"{expected.gate_id}: unsupported submission fields: {', '.join(unsupported)}"
        )
    missing = sorted(SUBMISSION_ALLOWED_FIELDS - set(submission))
    if missing:
        blockers.append(f"{expected.gate_id}: missing submission fields: {', '.join(missing)}")

    if submission.get("gate_id") != expected.gate_id:
        blockers.append(f"{expected.gate_id}: gate_id mismatch")
    if submission.get("response_packet_type") != expected.response_packet_type:
        blockers.append(f"{expected.gate_id}: response_packet_type mismatch")

    run_id, run_blockers = _safe_identifier(
        submission.get("operator_run_id"), f"{expected.gate_id}: operator_run_id"
    )
    blockers.extend(run_blockers)

    output_path, output_blockers = _safe_relative_path(
        submission.get("output_dir"), f"{expected.gate_id}: output_dir"
    )
    blockers.extend(output_blockers)
    if output_path is not None:
        expected_real_parts = tuple(Path(expected.real_root).parts)
        relative_parts = output_path.parts[len(expected_real_parts) :]
        if (
            len(output_path.parts) <= len(expected_real_parts)
            or output_path.parts[: len(expected_real_parts)] != expected_real_parts
        ):
            blockers.append(f"{expected.gate_id}: output_dir must live under {expected.real_root}")
        elif len(relative_parts) != 1:
            blockers.append(
                f"{expected.gate_id}: output_dir must be exactly "
                f"{expected.real_root}/<operator_run_id>"
            )
        elif run_id is not None and relative_parts[0] != run_id:
            blockers.append(
                f"{expected.gate_id}: output_dir final segment must match operator_run_id"
            )

    response_path, response_blockers = _safe_relative_path(
        submission.get("response_packet"), f"{expected.gate_id}: response_packet"
    )
    blockers.extend(response_blockers)
    if response_path is not None:
        if str(response_path) == expected.response_packet_for("OPERATOR_RUN_ID"):
            blockers.append(f"{expected.gate_id}: response_packet placeholder was not replaced")
        if output_path is not None:
            if response_path.parent != output_path:
                blockers.append(
                    f"{expected.gate_id}: response_packet must live directly under output_dir"
                )
            if response_path.name != OPERATOR_RESPONSE_PACKET_FILENAME:
                blockers.append(
                    f"{expected.gate_id}: response_packet filename must be "
                    f"{OPERATOR_RESPONSE_PACKET_FILENAME}"
                )
        if require_existing_response_packets and not (ROOT / response_path).is_file():
            blockers.append(f"{expected.gate_id}: response_packet file is missing")

    manifest_path, manifest_blockers = _safe_work_packets_path(
        submission.get("assembly_manifest_output"),
        f"{expected.gate_id}: assembly_manifest_output",
    )
    blockers.extend(manifest_blockers)
    if manifest_path is not None:
        if str(manifest_path) != expected.assembly_manifest_output:
            blockers.append(f"{expected.gate_id}: assembly_manifest_output mismatch")

    if blockers:
        return None, blockers
    assert run_id is not None
    assert response_path is not None
    assert output_path is not None
    assert manifest_path is not None
    command = (
        f"python3 {expected.intake_script} "
        f"--work-packet {expected.work_packet_path} "
        f"--response-packet {response_path} "
        f"--output-dir {output_path} "
        f"--assembly-manifest-output {manifest_path}"
    )
    return {
        "gate_id": expected.gate_id,
        "operator_run_id": run_id,
        "response_packet": str(response_path),
        "response_packet_type": expected.response_packet_type,
        "output_dir": str(output_path),
        "assembly_manifest_output": str(manifest_path),
        "intake_command": command,
        "writes_canonical_packet": False,
        "canonical_packet_not_written": expected.canonical_packet,
        "counts_as_acceptance_gate": False,
    }, []


def validate_manifest(
    manifest: dict[str, Any],
    *,
    require_existing_response_packets: bool = True,
) -> dict[str, Any]:
    blockers: list[str] = []
    unsupported_top = sorted(set(manifest) - TOP_LEVEL_ALLOWED_FIELDS)
    if unsupported_top:
        blockers.append("unsupported top-level fields: " + ", ".join(unsupported_top))
    if manifest.get("manifest_type") != MANIFEST_TYPE:
        blockers.append("manifest_type mismatch")
    _validate_claim_boundary(manifest, blockers)

    submissions = manifest.get("submissions")
    if not isinstance(submissions, list):
        blockers.append("submissions must be a list")
        submissions = []
    if len(submissions) != len(EXPECTED_SUBMISSIONS):
        blockers.append("submissions must contain exactly the four remaining KG gates")

    observed_gate_ids = [
        row.get("gate_id") if isinstance(row, dict) else None for row in submissions
    ]
    expected_gate_ids = [row.gate_id for row in EXPECTED_SUBMISSIONS]
    if observed_gate_ids != expected_gate_ids:
        blockers.append("submission gate order must match the remaining KG gate order")

    validated_submissions: list[dict[str, Any]] = []
    for index, expected in enumerate(EXPECTED_SUBMISSIONS):
        submission = submissions[index] if index < len(submissions) else None
        validated, row_blockers = _validate_submission(
            submission,
            expected,
            require_existing_response_packets=require_existing_response_packets,
        )
        blockers.extend(row_blockers)
        if validated is not None:
            validated_submissions.append(validated)

    return {
        "artifact_id": "kg_real_evidence_submission_manifest_validation_v1",
        "manifest_type": MANIFEST_TYPE,
        "valid": not blockers,
        "blockers": blockers,
        "authority": {
            "accepts_evidence": False,
            "promotes_evidence": False,
            "writes_candidate_artifacts": False,
            "writes_canonical_packets": False,
            "counts_as_acceptance_gate": False,
        },
        "intake_commands": [row["intake_command"] for row in validated_submissions]
        if not blockers
        else [],
        "validated_submissions": validated_submissions if not blockers else [],
    }


def safe_template_output(path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ManifestError("template output must be a non-empty string")
    if _forbidden_marker(path_value):
        raise ManifestError("template output must be a safe repo-relative path")
    path = Path(path_value)
    if path.is_absolute() or "." in path.parts or ".." in path.parts:
        raise ManifestError("template output must not be absolute or use dot segments")
    if not path.parts or path.parts[0] != "work_packets":
        raise ManifestError("template output must live under work_packets/")
    if any(part in FORBIDDEN_PATH_PARTS - {"templates"} for part in path.parts):
        raise ManifestError("template output must not use runtime output paths")
    current = ROOT
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ManifestError("template output symlink components are not accepted")
    resolved = (ROOT / path).resolve()
    try:
        resolved.relative_to(WORK_PACKETS.resolve())
    except ValueError as exc:
        raise ManifestError("template output escapes work_packets/") from exc
    if path.suffix != ".json":
        raise ManifestError("template output must be a JSON file")
    if path != DEFAULT_TEMPLATE_OUTPUT.relative_to(ROOT):
        raise ManifestError("template output must be the tracked submission manifest template path")
    return ROOT / path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", help="operator submission manifest JSON to validate")
    parser.add_argument(
        "--emit-template",
        action="store_true",
        help="write the tracked non-evidence submission manifest template",
    )
    parser.add_argument(
        "--check-template",
        action="store_true",
        help="exit nonzero if the tracked submission manifest template is stale",
    )
    parser.add_argument(
        "--template-output",
        default=str(DEFAULT_TEMPLATE_OUTPUT.relative_to(ROOT)),
        help="tracked submission manifest template output path",
    )
    parser.add_argument(
        "--no-require-existing-response-packets",
        action="store_true",
        help="validate path contracts without checking response packet existence",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    template_output = safe_template_output(args.template_output)
    template = build_template()
    if args.emit_template:
        template_output.parent.mkdir(parents=True, exist_ok=True)
        template_output.write_text(_json_text(template), encoding="utf-8")
        print(
            json.dumps(
                {
                    "artifact_id": "kg_real_evidence_submission_manifest_template_v1",
                    "output": str(template_output.relative_to(ROOT)),
                    "authority": validate_manifest(
                        {
                            "manifest_type": MANIFEST_TYPE,
                            "submissions": [],
                            "claim_boundary": template["claim_boundary"],
                        },
                        require_existing_response_packets=False,
                    )["authority"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.check_template:
        current = template_output.read_text(encoding="utf-8") if template_output.exists() else None
        up_to_date = current == _json_text(template)
        print(
            json.dumps(
                {
                    "artifact_id": "kg_real_evidence_submission_manifest_template_check_v1",
                    "output": str(template_output.relative_to(ROOT)),
                    "exists": template_output.exists(),
                    "up_to_date": up_to_date,
                },
                indent=2,
                sort_keys=True,
            )
        )
        if not up_to_date:
            print(
                "submission manifest template is stale; rerun "
                "real_evidence_submission_manifest.py --emit-template",
                file=sys.stderr,
            )
            return 1
        return 0
    if not args.manifest:
        raise ManifestError("either --manifest, --emit-template, or --check-template is required")
    report = validate_manifest(
        load_json_file(Path(args.manifest)),
        require_existing_response_packets=not args.no_require_existing_response_packets,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ManifestError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
