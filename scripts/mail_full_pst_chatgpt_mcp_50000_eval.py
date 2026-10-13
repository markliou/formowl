#!/usr/bin/env python3
"""Run a grounded ChatGPT x FormOwl MCP offline evaluation.

This evaluator expands each reviewer-grounded private MAY domain-hard case into
500 deterministic ChatGPT usage contexts. The production run rebuilds or loads
the MAY mail evidence bundle and executes the 100 unique evidence cases through
the real in-process Semantic MCP JSON-RPC gateway. Presentation variants remain
rendered scenarios rather than independent evidence cases. Candidate-KG,
ontology, and the ordered 326-arm factorial retain their source-report bindings.

Private query text, trajectories, and concrete observation/message identifiers
are written only below ``--private-dir``. The public report contains hashes,
counts, statuses, explicit simulated costs, measured evaluator performance, and
aggregate comparisons.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import product
import json
import os
from pathlib import Path
import re
import resource
import secrets
import sys
import time
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    ContractValidationError,
    assert_no_public_raw_references,
    sha256_json,
    to_plain,
)
from formowl_evaluator import (  # noqa: E402
    ReplayArtifact,
    ReplayCase,
    execute_mail_evidence_replays,
    load_or_rebuild_may_mail_evidence_bundle,
    load_replay_artifact,
    load_replay_artifact_for_repair,
    repair_mail_evidence_replays,
    validate_replay_artifact,
    write_replay_artifact,
)
from formowl_kg_eval.evidence_answer import (  # noqa: E402
    EvidenceDocument,
    build_prediction_from_evidence,
    build_private_gold_from_evidence,
    evidence_documents_from_bundle,
)
from formowl_kg_eval.structured_answer import (  # noqa: E402
    PrivateStructuredAnswerGold,
    StructuredAnswerPrediction,
    score_structured_answer,
)
from formowl_graph import (  # noqa: E402
    build_default_candidate_evidence_harness_contract,
    require_default_candidate_evidence_harness_contract,
)
from formowl_mail import MailEvidenceBundle  # noqa: E402

SCRIPTS_ROOT = ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import mail_full_pst_domain_hard_case_eval as baseline_eval  # noqa: E402
import mail_full_pst_domain_hard_kg_fusion_eval as kg_eval  # noqa: E402
import mail_full_pst_domain_hard_ontology_ablation_eval as ontology_eval  # noqa: E402
import mail_full_pst_domain_hard_ontology_factorial_eval as factorial_eval  # noqa: E402


HARNESS_CONTRACT = build_default_candidate_evidence_harness_contract()
require_default_candidate_evidence_harness_contract(HARNESS_CONTRACT)

DEFAULT_PRIVATE_MANIFEST = (
    ROOT
    / ".test-tmp"
    / "procurement-backup-may-domain-hard-work"
    / "artifacts"
    / "domain_hard_case_manifest.private.json"
)
DEFAULT_BASELINE_REPORT = ROOT / ".test-tmp" / "procurement-backup-may-domain-hard-baseline.json"
DEFAULT_KG_FUSION_REPORT = ROOT / ".test-tmp" / "procurement-backup-may-domain-hard-kg-fusion.json"
DEFAULT_ONTOLOGY_ABLATION_REPORT = (
    ROOT / ".test-tmp" / "procurement-backup-may-domain-hard-ontology-ablation.json"
)
DEFAULT_ONTOLOGY_FACTORIAL_REPORT = (
    ROOT / ".test-tmp" / "procurement-backup-may-domain-hard-ontology-factorial.json"
)
DEFAULT_PRIVATE_DIR = ROOT / ".test-tmp" / "formowl-mail-chatgpt-mcp-50000-private"
DEFAULT_OUTPUT = ROOT / ".test-tmp" / "formowl-mail-chatgpt-mcp-50000-eval.json"
DEFAULT_CORPUS_ROOT = DEFAULT_PRIVATE_MANIFEST.parents[1]
DEFAULT_BUNDLE_CACHE_FILENAME = "may-mail-evidence-bundle.private.json"
DEFAULT_REPLAY_CACHE_FILENAME = "may-mail-jsonrpc-replay.private.json"

REPORT_TYPE = "mail_full_pst_chatgpt_mcp_50000_offline_eval"
PRIVATE_MANIFEST_TYPE = "mail_full_pst_chatgpt_mcp_50000_private_manifest"
PRIVATE_ROWS_TYPE = "mail_full_pst_chatgpt_mcp_50000_private_rows"
POLICY_VERSION = "formowl_chatgpt_mcp_offline_50000_v1"
GENERATED_AT = "2026-07-10T00:00:00+00:00"
RUN_OPT_IN_ENV = "FORMOWL_RUN_MAIL_FULL_PST_CHATGPT_MCP_50000_EVAL"

PRODUCTION_BASE_CASE_COUNT = 100
PRODUCTION_SCENARIOS_PER_BASE_CASE = 500
PRODUCTION_CASE_COUNT = 50_000
EXPECTED_FACTORIAL_ARM_COUNT = 326

PERSONAS = (
    "procurement_manager",
    "finance_reviewer",
    "operations_lead",
    "technical_program_manager",
    "executive_sponsor",
)
URGENCIES = ("routine", "today", "urgent", "incident")
ANSWER_FORMATS = ("brief", "bullets", "table", "decision_memo", "action_plan")
CONVERSATION_STYLES = (
    "single_turn",
    "clarification_then_tool",
    "follow_up_refinement",
    "correction_after_no_match",
    "permission_boundary_follow_up",
)

DEFAULT_DIMENSIONS = {
    "personas": PERSONAS,
    "urgencies": URGENCIES,
    "answer_formats": ANSWER_FORMATS,
    "conversation_styles": CONVERSATION_STYLES,
}

CHATGPT_WITHOUT_FORMOWL = "chatgpt_without_formowl"
CHATGPT_WITH_MAIL_EVIDENCE = "chatgpt_with_mail_evidence"
CHATGPT_WITH_CANDIDATE_KG = "chatgpt_with_candidate_kg"
CHATGPT_WITH_ONTOLOGY_GUIDED_KG = "chatgpt_with_ontology_guided_kg"
MAJOR_ARMS = (
    CHATGPT_WITHOUT_FORMOWL,
    CHATGPT_WITH_MAIL_EVIDENCE,
    CHATGPT_WITH_CANDIDATE_KG,
    CHATGPT_WITH_ONTOLOGY_GUIDED_KG,
)

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_NOT_APPLICABLE = "not_applicable"
VALID_STATUSES = {STATUS_PASSED, STATUS_FAILED, STATUS_NOT_APPLICABLE}
RESULT_KINDS = {"owner_match", "no_match", "permission_denied"}
PRIVATE_MANIFEST_FILENAME = "chatgpt_mcp_50000_manifest.private.json"
PRIVATE_ROWS_FILENAME = "chatgpt_mcp_50000_rows.private.json"
MAX_PUBLIC_REPORT_BYTES = 5 * 1024 * 1024

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_PUBLIC_KEY_PARTS = {
    "body",
    "content",
    "email",
    "forbidden_source",
    "message_id",
    "observation_id",
    "query_text",
    "required_source",
    "source_id",
    "user_query",
}
_FORBIDDEN_PUBLIC_EXACT_KEYS = {"trajectory", "trajectories"}
_BLOCKED_REASONS = {
    "explicit_run_flag_required",
    "offline_eval_requires_explicit_opt_in",
    "private_manifest_missing",
    "baseline_report_missing",
    "kg_fusion_report_missing",
    "ontology_ablation_report_missing",
    "ontology_factorial_report_missing",
    "private_manifest_invalid",
    "baseline_report_invalid",
    "kg_fusion_report_invalid",
    "ontology_ablation_report_invalid",
    "ontology_factorial_report_invalid",
    "source_manifest_hash_mismatch",
    "source_case_binding_mismatch",
    "private_dir_required",
    "offline_eval_failed",
}


@dataclass(frozen=True)
class ExpansionDimensions:
    personas: tuple[str, ...]
    urgencies: tuple[str, ...]
    answer_formats: tuple[str, ...]
    conversation_styles: tuple[str, ...]

    @property
    def product_size(self) -> int:
        return (
            len(self.personas)
            * len(self.urgencies)
            * len(self.answer_formats)
            * len(self.conversation_styles)
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "persona_count": len(self.personas),
            "urgency_count": len(self.urgencies),
            "answer_format_count": len(self.answer_formats),
            "conversation_style_count": len(self.conversation_styles),
            "scenario_product": self.product_size,
            "dimension_value_hash": sha256_json(
                {
                    "personas": list(self.personas),
                    "urgencies": list(self.urgencies),
                    "answer_formats": list(self.answer_formats),
                    "conversation_styles": list(self.conversation_styles),
                }
            ),
        }


@dataclass(frozen=True)
class SourceBundle:
    manifest: dict[str, Any]
    baseline: dict[str, Any]
    kg_fusion: dict[str, Any]
    ontology_ablation: dict[str, Any]
    ontology_factorial: dict[str, Any]


def default_dimensions() -> ExpansionDimensions:
    return ExpansionDimensions(
        personas=PERSONAS,
        urgencies=URGENCIES,
        answer_formats=ANSWER_FORMATS,
        conversation_styles=CONVERSATION_STYLES,
    )


def run_chatgpt_mcp_50000_eval(
    *,
    private_manifest_path: Path = DEFAULT_PRIVATE_MANIFEST,
    baseline_report_path: Path = DEFAULT_BASELINE_REPORT,
    kg_fusion_report_path: Path = DEFAULT_KG_FUSION_REPORT,
    ontology_ablation_report_path: Path = DEFAULT_ONTOLOGY_ABLATION_REPORT,
    ontology_factorial_report_path: Path = DEFAULT_ONTOLOGY_FACTORIAL_REPORT,
    private_dir: Path | None = DEFAULT_PRIVATE_DIR,
    dimensions: ExpansionDimensions | None = None,
    expected_base_case_count: int = PRODUCTION_BASE_CASE_COUNT,
    corpus_root: Path = DEFAULT_CORPUS_ROOT,
    bundle_cache_path: Path | None = None,
    replay_cache_path: Path | None = None,
) -> dict[str, Any]:
    """Run the deterministic evaluator after the explicit environment opt-in."""

    if os.environ.get(RUN_OPT_IN_ENV) != "1":
        return _blocked_report("offline_eval_requires_explicit_opt_in")
    if private_dir is None:
        return _blocked_report("private_dir_required")
    evaluation_started_at = time.perf_counter()
    try:
        sources = _load_and_validate_sources(
            private_manifest_path=private_manifest_path,
            baseline_report_path=baseline_report_path,
            kg_fusion_report_path=kg_fusion_report_path,
            ontology_ablation_report_path=ontology_ablation_report_path,
            ontology_factorial_report_path=ontology_factorial_report_path,
            expected_base_case_count=expected_base_case_count,
        )
        replay_artifact = None
        replay_mode = "not_run"
        replay_repair_summary = None
        grounded_answer_evaluation = None
        if expected_base_case_count == PRODUCTION_BASE_CASE_COUNT:
            cases = _validate_private_manifest(sources.manifest, expected_base_case_count)
            replay_cases = [ReplayCase.from_private_manifest_row(case) for case in cases]
            stateful_follow_ups = _stateful_follow_up_case_fingerprints(replay_cases)
            resolved_replay_cache = (
                replay_cache_path
                if replay_cache_path is not None
                else private_dir / DEFAULT_REPLAY_CACHE_FILENAME
            )
            bundle = load_or_rebuild_may_mail_evidence_bundle(
                corpus_root,
                sources.manifest,
                cache_path=(
                    bundle_cache_path
                    if bundle_cache_path is not None
                    else private_dir / DEFAULT_BUNDLE_CACHE_FILENAME
                ),
            )
            if resolved_replay_cache.exists():
                try:
                    replay_artifact = load_replay_artifact(resolved_replay_cache)
                    replay_mode = "validated_private_replay"
                except ContractValidationError:
                    repair_source = load_replay_artifact_for_repair(resolved_replay_cache)
                    replay_artifact, replay_repair_summary = repair_mail_evidence_replays(
                        repair_source,
                        bundle,
                        replay_cases,
                        now="2026-07-07T12:00:00+00:00",
                        stateful_follow_up_case_fingerprints=stateful_follow_ups,
                    )
                    write_replay_artifact(resolved_replay_cache, replay_artifact)
                    replay_mode = "repaired_live_in_process"
            else:
                replay_artifact = execute_mail_evidence_replays(
                    bundle,
                    replay_cases,
                    now="2026-07-07T12:00:00+00:00",
                    stateful_follow_up_case_fingerprints=stateful_follow_ups,
                )
                write_replay_artifact(resolved_replay_cache, replay_artifact)
                replay_mode = "executed_live_in_process"
            expected_fingerprints = {str(case["private_fingerprint"]) for case in cases}
            replay_fingerprints = {
                str(row.get("case_fingerprint")) for row in replay_artifact.public_rows
            }
            if (
                replay_artifact.unique_evidence_case_count != len(cases)
                or replay_fingerprints != expected_fingerprints
            ):
                raise RuntimeError("replay cache does not match private manifest")
            grounded_answer_evaluation = _build_grounded_answer_evaluation(
                bundle=bundle,
                cases=cases,
                replay_artifact=replay_artifact,
                corpus_root=corpus_root,
            )
        return _run_eval_inner(
            sources=sources,
            private_dir=private_dir,
            dimensions=dimensions or default_dimensions(),
            expected_base_case_count=expected_base_case_count,
            replay_artifact=replay_artifact,
            grounded_answer_evaluation=grounded_answer_evaluation,
            evaluation_started_at=evaluation_started_at,
            replay_mode=replay_mode,
            replay_repair_summary=replay_repair_summary,
        )
    except FileNotFoundError as exc:
        reason = str(exc)
        return _blocked_report(reason if reason in _BLOCKED_REASONS else "offline_eval_failed")
    except (RuntimeError, ValueError):
        return _blocked_report("offline_eval_failed")


def _load_and_validate_sources(
    *,
    private_manifest_path: Path,
    baseline_report_path: Path,
    kg_fusion_report_path: Path,
    ontology_ablation_report_path: Path,
    ontology_factorial_report_path: Path,
    expected_base_case_count: int,
) -> SourceBundle:
    manifest = _read_json(private_manifest_path, "private_manifest_missing")
    baseline = _read_json(baseline_report_path, "baseline_report_missing")
    kg_fusion = _read_json(kg_fusion_report_path, "kg_fusion_report_missing")
    ontology_ablation = _read_json(
        ontology_ablation_report_path,
        "ontology_ablation_report_missing",
    )
    ontology_factorial = _read_json(
        ontology_factorial_report_path,
        "ontology_factorial_report_missing",
    )

    cases = _validate_private_manifest(manifest, expected_base_case_count)
    manifest_hash = sha256_json(manifest)
    baseline_rows = _validated_rows(
        baseline,
        rows_key="case_rows",
        status_key="status",
        expected_count=expected_base_case_count,
        invalid_reason="baseline_report_invalid",
    )
    kg_rows = _validated_rows(
        kg_fusion,
        rows_key="case_rows",
        status_key="kg_status",
        expected_count=expected_base_case_count,
        invalid_reason="kg_fusion_report_invalid",
    )
    ontology_rows = _validated_rows(
        ontology_ablation,
        rows_key="ablation_rows",
        status_key="ontology_status",
        expected_count=expected_base_case_count,
        invalid_reason="ontology_ablation_report_invalid",
    )
    factorial_summaries = _factorial_summaries(ontology_factorial)

    for report, module, invalid_reason in (
        (baseline, baseline_eval, "baseline_report_invalid"),
        (kg_fusion, kg_eval, "kg_fusion_report_invalid"),
        (ontology_ablation, ontology_eval, "ontology_ablation_report_invalid"),
        (ontology_factorial, factorial_eval, "ontology_factorial_report_invalid"),
    ):
        report_manifest_hash = _safe_outputs(report).get("private_manifest_hash")
        if report_manifest_hash != manifest_hash:
            raise FileNotFoundError("source_manifest_hash_mismatch")
        if expected_base_case_count == PRODUCTION_BASE_CASE_COUNT:
            stored_validation = report.get("validation")
            recomputed_validation = module.validate_report(report)
            if (
                report.get("report_type") != module.REPORT_TYPE
                or not isinstance(stored_validation, Mapping)
                or stored_validation.get("passed") is not True
                or recomputed_validation.get("passed") is not True
            ):
                raise FileNotFoundError(invalid_reason)
        elif not isinstance(report.get("report_type"), str):
            raise FileNotFoundError(invalid_reason)

    expected_fingerprints = {str(case["private_fingerprint"]) for case in cases}
    row_sets = (
        {str(row["case_manifest_entry_hash"]) for row in baseline_rows},
        {str(row["case_manifest_entry_hash"]) for row in kg_rows},
        {str(row["case_manifest_entry_hash"]) for row in ontology_rows},
    )
    if any(row_set != expected_fingerprints for row_set in row_sets):
        raise FileNotFoundError("source_case_binding_mismatch")
    if len(factorial_summaries) != EXPECTED_FACTORIAL_ARM_COUNT:
        raise FileNotFoundError("ontology_factorial_report_invalid")

    return SourceBundle(
        manifest=manifest,
        baseline=baseline,
        kg_fusion=kg_fusion,
        ontology_ablation=ontology_ablation,
        ontology_factorial=ontology_factorial,
    )


def _run_eval_inner(
    *,
    sources: SourceBundle,
    private_dir: Path,
    dimensions: ExpansionDimensions,
    expected_base_case_count: int,
    replay_artifact: ReplayArtifact | None = None,
    grounded_answer_evaluation: Mapping[str, Any] | None = None,
    evaluation_started_at: float | None = None,
    replay_mode: str = "not_run",
    replay_repair_summary: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    started_at = evaluation_started_at or time.perf_counter()
    if dimensions.product_size <= 0:
        raise ValueError("empty expansion dimensions")
    cases = _validate_private_manifest(sources.manifest, expected_base_case_count)
    baseline_rows = _rows_by_fingerprint(sources.baseline, "case_rows")
    kg_rows = _rows_by_fingerprint(sources.kg_fusion, "case_rows")
    ontology_rows = _rows_by_fingerprint(sources.ontology_ablation, "ablation_rows")
    grounded_scores = _grounded_arm_scores_by_fingerprint(grounded_answer_evaluation)
    if grounded_answer_evaluation is not None and set(grounded_scores) != {
        str(case["private_fingerprint"]) for case in cases
    }:
        raise ValueError("grounded answer rows do not match private manifest")
    replay_semantics = (
        {
            str(row["case_fingerprint"]): str(row["semantic_kind"])
            for row in replay_artifact.public_rows
        }
        if replay_artifact is not None
        else {}
    )
    tools_list_response = (
        replay_artifact.tools_list_response
        if replay_artifact is not None
        else _simulation_tools_list_response()
    )

    public_rows: list[dict[str, Any]] = []
    private_manifest_rows: list[dict[str, Any]] = []
    private_result_rows: list[dict[str, Any]] = []
    for base_index, case in enumerate(cases):
        fingerprint = str(case["private_fingerprint"])
        source_rows = {
            CHATGPT_WITH_MAIL_EVIDENCE: baseline_rows[fingerprint],
            CHATGPT_WITH_CANDIDATE_KG: kg_rows[fingerprint],
            CHATGPT_WITH_ONTOLOGY_GUIDED_KG: ontology_rows[fingerprint],
        }
        for scenario_index, scenario in enumerate(_iter_scenarios(dimensions)):
            expanded = _expanded_case(
                case=case,
                base_index=base_index,
                scenario_index=scenario_index,
                scenario=scenario,
                source_rows=source_rows,
                structured_scores=grounded_scores.get(fingerprint, {}),
                actual_mail_result_kind=replay_semantics.get(
                    fingerprint,
                    str(case["result_kind"]),
                ),
                tools_list_response=tools_list_response,
            )
            public_rows.append(expanded["public_row"])
            private_manifest_rows.append(expanded["private_manifest_row"])
            private_result_rows.append(expanded["private_result_row"])

    source_binding = _source_binding(sources)
    private_manifest_rows_hash = sha256_json(private_manifest_rows)
    private_result_rows_hash = sha256_json(private_result_rows)
    private_manifest_payload = {
        "manifest_type": PRIVATE_MANIFEST_TYPE,
        "policy_version": POLICY_VERSION,
        "generated_at": GENERATED_AT,
        "source_private_manifest_hash": sha256_json(sources.manifest),
        "source_binding_hash": sha256_json(source_binding),
        "private_manifest_rows_hash": private_manifest_rows_hash,
        "private_result_rows_hash": private_result_rows_hash,
        "unique_evidence_case_count": len(cases),
        "rendered_scenario_count": len(private_manifest_rows),
        "base_case_count": len(cases),
        "scenario_count_per_base_case": dimensions.product_size,
        "expanded_case_count": len(private_manifest_rows),
        "dimensions": {
            "personas": list(dimensions.personas),
            "urgencies": list(dimensions.urgencies),
            "answer_formats": list(dimensions.answer_formats),
            "conversation_styles": list(dimensions.conversation_styles),
        },
        "cases": private_manifest_rows,
    }
    private_rows_payload = {
        "rows_type": PRIVATE_ROWS_TYPE,
        "policy_version": POLICY_VERSION,
        "generated_at": GENERATED_AT,
        "source_binding_hash": sha256_json(source_binding),
        "private_manifest_rows_hash": private_manifest_rows_hash,
        "private_result_rows_hash": private_result_rows_hash,
        "unique_evidence_case_count": len(cases),
        "rendered_scenario_count": len(private_result_rows),
        "expanded_case_count": len(private_result_rows),
        "rows": private_result_rows,
        "mcp_replay": _private_replay_payload(replay_artifact),
        "replay_repair_summary": (
            dict(replay_repair_summary) if replay_repair_summary is not None else None
        ),
        "grounded_answer_evaluation": grounded_answer_evaluation,
    }
    private_manifest_path = private_dir / PRIVATE_MANIFEST_FILENAME
    private_rows_path = private_dir / PRIVATE_ROWS_FILENAME
    private_serialized_sizes = _write_private_artifacts_atomic(
        private_dir,
        {
            PRIVATE_MANIFEST_FILENAME: private_manifest_payload,
            PRIVATE_ROWS_FILENAME: private_rows_payload,
        },
    )

    arm_aggregates = _aggregate_arm_rows(public_rows)
    factorial_summary = _factorial_summary(
        sources.ontology_factorial,
        scenario_multiplier=dimensions.product_size,
        major_arm_aggregates=arm_aggregates,
    )
    source_hashes = dict(source_binding["source_hashes"])
    safe_outputs = {
        "policy_hash": sha256_json(POLICY_VERSION),
        "evaluation_profile": (
            "production_50000"
            if len(cases) == PRODUCTION_BASE_CASE_COUNT
            and dimensions.product_size == PRODUCTION_SCENARIOS_PER_BASE_CASE
            else "unit_scaled"
        ),
        "deterministic_model_free_simulation": True,
        "source_hashes": source_hashes,
        "dimension_summary": dimensions.to_public_dict(),
        "stateful_trajectory_summary": {
            "rendered_variants_only": True,
            "unique_evidence_case_template_count": len(cases),
            "conversation_style_counts": dict(
                sorted(
                    Counter(
                        str(row["scenario"]["conversation_style"]) for row in private_manifest_rows
                    ).items()
                )
            ),
            "rendered_response_conditioned_follow_up_scenario_count": sum(
                len(_trajectory_tool_calls(row["trajectory"])) > 1 for row in private_manifest_rows
            ),
            "rendered_condition_not_triggered_scenario_count": sum(
                _trajectory_condition(row["trajectory"]) is not None
                and _trajectory_condition(row["trajectory"]).get("triggered") is False
                for row in private_manifest_rows
            ),
            "rendered_clarification_exchange_scenario_count": sum(
                _trajectory_has_clarification(row["trajectory"]) for row in private_manifest_rows
            ),
            "rendered_tool_contract_passed_scenario_count": sum(
                row.get("tool_selection_status") == STATUS_PASSED
                and row.get("argument_contract_status") == STATUS_PASSED
                for row in private_manifest_rows
            ),
            "condition_outcome_counts": dict(
                sorted(
                    Counter(
                        (
                            f"{condition.get('required_result_kind')}<-"
                            f"{condition.get('actual_result_kind')}:"
                            f"{'triggered' if condition.get('triggered') else 'not_triggered'}"
                        )
                        for row in private_manifest_rows
                        if (condition := _trajectory_condition(row["trajectory"])) is not None
                    ).items()
                )
            ),
            "trajectory_root_hash": sha256_json(
                [row["trajectory"] for row in private_manifest_rows]
            ),
            "executed_unique_case_follow_up_count": sum(
                int(row.get("step_count", 0)) > 1 for row in replay_artifact.public_rows
            )
            if replay_artifact is not None
            else 0,
            "executed_follow_ups_are_response_derived": replay_artifact is not None,
            "executed_follow_ups_use_same_bound_session": replay_artifact is not None,
            "executed_follow_up_trajectory_root_hash": (
                sha256_json(
                    [
                        row["trajectory_root_hash"]
                        for row in replay_artifact.public_rows
                        if int(row.get("step_count", 0)) > 1
                    ]
                )
                if replay_artifact is not None
                else None
            ),
        },
        "unique_evidence_case_count": len(cases),
        "rendered_scenario_count": len(public_rows),
        "rendered_scenarios_are_not_independent_evidence_cases": True,
        "base_case_count": len(cases),
        "scenario_count_per_base_case": dimensions.product_size,
        "expanded_case_count": len(public_rows),
        "major_arm_count": len(MAJOR_ARMS),
        "major_arm_names": list(MAJOR_ARMS),
        "private_row_count": len(public_rows),
        "private_public_row_hash": sha256_json(public_rows),
        "private_public_row_hash_sequence_hash": sha256_json(
            [row["row_hash"] for row in public_rows]
        ),
        "unique_expanded_case_hash_count": len({row["expanded_case_hash"] for row in public_rows}),
        "result_kind_counts": dict(
            sorted(Counter(row["result_kind"] for row in public_rows).items())
        ),
        "arm_aggregates": arm_aggregates,
        "factorial_aggregate_summary": factorial_summary,
        "grounded_mcp_replay": _public_replay_summary(
            replay_artifact,
            mode=replay_mode,
            repair_summary=replay_repair_summary,
        ),
        "grounded_answer_evaluation": _public_grounded_answer_summary(grounded_answer_evaluation),
        "mail_case_progress_tool_assessment": {
            "status": "blocked_not_case_scoped",
            "evaluated_as_answer_arm": False,
            "reason_hash": sha256_json(
                "answer_mail_case_progress currently scans the full visible bundle"
            ),
        },
        "private_artifact_manifest_hash": sha256_json(private_manifest_payload),
        "private_artifact_rows_hash": sha256_json(private_rows_payload),
        "private_artifact_file_count": 2,
        "source_binding_hash": sha256_json(source_binding),
        "serialized_sizes_bytes": {
            "private_manifest": private_serialized_sizes[PRIVATE_MANIFEST_FILENAME],
            "private_rows": private_serialized_sizes[PRIVATE_ROWS_FILENAME],
            "public_report_without_validation": 0,
        },
        "measured_performance": {
            "wall_time_ms": max(0, int((time.perf_counter() - started_at) * 1000)),
            "peak_rss_bytes": _peak_rss_bytes(),
        },
    }
    metrics = {
        "source_private_manifest_loaded": True,
        "source_reports_loaded": True,
        "source_reports_bound_to_same_manifest": True,
        "source_report_validators_recomputed": True,
        "source_case_status_hash_rows_bound": True,
        "real_mcp_jsonrpc_replay_completed": replay_artifact is not None,
        "grounded_structured_answer_scoring_completed": (grounded_answer_evaluation is not None),
        "answer_quality_derived_only_from_structured_oracle": True,
        "answer_usefulness_and_safety_aggregated_separately": True,
        "deterministic_expansion_generated": True,
        "scenario_product_exact": dimensions.product_size
        == (
            len(dimensions.personas)
            * len(dimensions.urgencies)
            * len(dimensions.answer_formats)
            * len(dimensions.conversation_styles)
        ),
        "production_case_count_is_50000": len(public_rows) == PRODUCTION_CASE_COUNT,
        "private_manifest_written": private_manifest_path.exists(),
        "private_rows_written": private_rows_path.exists(),
        "private_files_mode_0600": all(
            (path.stat().st_mode & 0o777) == 0o600
            for path in (private_manifest_path, private_rows_path)
        ),
        "private_atomic_transaction_completed": True,
        "public_report_excludes_private_query_and_ids": True,
        "factorial_326_arms_integrated_at_aggregate_only": factorial_summary["arm_count"]
        == EXPECTED_FACTORIAL_ARM_COUNT,
        "factorial_per_case_rows_not_claimed": True,
        "model_free_simulation_disclosed": True,
        "live_chatgpt_quality_not_claimed": True,
        "row_derived_validation_recomputed": True,
        "full_private_source_binding_validated": True,
        "public_report_bounded_to_5_mib": True,
        "raw_leak_guard_passed": True,
        "offline_eval_completed": True,
    }
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": GENERATED_AT,
        "metrics": metrics,
        "safe_outputs": safe_outputs,
        "claim_boundary": _claim_boundary(
            True,
            supports_grounded_replay=replay_artifact is not None,
        ),
    }
    _stabilize_public_core_size(report)
    _assert_no_source_secrets(report, sources.manifest)
    report["validation"] = validate_report(
        report,
        private_manifest_payload=private_manifest_payload,
        private_rows_payload=private_rows_payload,
        sources=sources,
        private_dir=private_dir,
        expected_replay_attestation_hash=(
            replay_artifact.attestation_hash if replay_artifact is not None else None
        ),
        expected_grounded_answer_evaluation=grounded_answer_evaluation,
    )
    if _serialized_json_size(report, compact=True) > MAX_PUBLIC_REPORT_BYTES:
        raise RuntimeError("public report exceeds bounded size")
    if not report["validation"]["passed"]:
        raise RuntimeError("derived report validation failed")
    return report


def _iter_scenarios(dimensions: ExpansionDimensions) -> Iterable[dict[str, str]]:
    for persona, urgency, answer_format, conversation_style in product(
        dimensions.personas,
        dimensions.urgencies,
        dimensions.answer_formats,
        dimensions.conversation_styles,
    ):
        yield {
            "persona": persona,
            "urgency": urgency,
            "answer_format": answer_format,
            "conversation_style": conversation_style,
        }


def _private_replay_payload(replay_artifact: ReplayArtifact | None) -> dict[str, Any] | None:
    if replay_artifact is None:
        return None
    return {
        "unique_evidence_case_count": replay_artifact.unique_evidence_case_count,
        "tools_list_response": replay_artifact.tools_list_response,
        "tools_list_response_hash": replay_artifact.tools_list_response_hash,
        "public_rows_root_hash": replay_artifact.public_rows_root_hash,
        "private_rows_root_hash": replay_artifact.private_rows_root_hash,
        "attestation_hash": replay_artifact.attestation_hash,
        "public_rows": list(replay_artifact.public_rows),
        "private_rows": list(replay_artifact.private_rows),
    }


def _public_replay_summary(
    replay_artifact: ReplayArtifact | None,
    *,
    mode: str = "not_run",
    repair_summary: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    if replay_artifact is None:
        return {
            "executed": False,
            "mode": "not_run",
            "unique_evidence_case_count": 0,
            "tools_list_response_hash": None,
            "public_rows_root_hash": None,
            "private_rows_root_hash": None,
            "attestation_hash": None,
            "external_trust_anchor_required": False,
            "response_status_counts": {},
            "error_count": 0,
            "evidence_count": 0,
            "citation_count": 0,
            "stateful_follow_up_case_count": 0,
            "stateful_follow_up_style_counts": {},
            "repair_summary": None,
        }
    return {
        "executed": True,
        "mode": mode,
        "unique_evidence_case_count": replay_artifact.unique_evidence_case_count,
        "tools_list_response_hash": replay_artifact.tools_list_response_hash,
        "public_rows_root_hash": replay_artifact.public_rows_root_hash,
        "private_rows_root_hash": replay_artifact.private_rows_root_hash,
        "attestation_hash": replay_artifact.attestation_hash,
        "external_trust_anchor_required": True,
        "response_status_counts": dict(
            sorted(
                Counter(
                    str(row.get("response_status")) for row in replay_artifact.public_rows
                ).items()
            )
        ),
        "expected_result_kind_counts": dict(
            sorted(
                Counter(
                    str(row.get("expected_result_kind")) for row in replay_artifact.public_rows
                ).items()
            )
        ),
        "actual_semantic_kind_counts": dict(
            sorted(
                Counter(
                    str(row.get("semantic_kind")) for row in replay_artifact.public_rows
                ).items()
            )
        ),
        "result_kind_match_count": sum(
            row.get("result_kind_match") is True for row in replay_artifact.public_rows
        ),
        "result_kind_mismatch_count": sum(
            row.get("result_kind_match") is False for row in replay_artifact.public_rows
        ),
        "error_count": sum(bool(row.get("is_error")) for row in replay_artifact.public_rows),
        "evidence_count": sum(
            int(row.get("evidence_count", 0)) for row in replay_artifact.public_rows
        ),
        "citation_count": sum(
            int(row.get("citation_count", 0)) for row in replay_artifact.public_rows
        ),
        "stateful_follow_up_case_count": sum(
            int(row.get("step_count", 0)) > 1 for row in replay_artifact.public_rows
        ),
        "stateful_follow_up_style_counts": dict(
            sorted(
                Counter(
                    str(row.get("follow_up_style"))
                    for row in replay_artifact.public_rows
                    if int(row.get("step_count", 0)) > 1
                ).items()
            )
        ),
        "repair_summary": dict(repair_summary) if repair_summary is not None else None,
    }


def _stateful_follow_up_case_fingerprints(cases: Sequence[ReplayCase]) -> set[str]:
    selected: dict[str, str] = {}
    for case in cases:
        selected.setdefault(case.result_kind, case.case_fingerprint)
    return set(selected.values())


def _build_grounded_answer_evaluation(
    *,
    bundle: MailEvidenceBundle | None,
    cases: Sequence[Mapping[str, Any]],
    replay_artifact: ReplayArtifact,
    corpus_root: Path,
) -> dict[str, Any]:
    replay_by_fingerprint = {
        str(row["case_fingerprint"]): row for row in replay_artifact.private_rows
    }
    segments = kg_eval._load_mail_segments(corpus_root)
    kg_index = kg_eval._build_candidate_kg_index(segments)
    ontology = ontology_eval._build_domain_ontology()
    ontology_index = ontology_eval._build_ontology_index(
        tuple(kg_index.segment_by_observation_id.values()),
        kg_index,
        ontology,
    )
    rows: list[dict[str, Any]] = []
    for case in cases:
        fingerprint = str(case["private_fingerprint"])
        result_kind = str(case["result_kind"])
        query_text = str(case["query_text"])
        case_id = str(case["case_id"])
        required_ids = tuple(
            str(value) for value in case.get("required_source_observation_ids", ())
        )
        gold = build_private_gold_from_evidence(
            case_id=case_id,
            result_kind=result_kind,
            query_text=query_text,
            documents=_evidence_documents(bundle, corpus_root, required_ids),
        )
        mail_replay = replay_by_fingerprint[fingerprint]
        mail_payload = _replay_tool_payload(mail_replay)
        mail_data = (
            mail_payload.get("data") if isinstance(mail_payload.get("data"), Mapping) else {}
        )
        actual_mail_result_kind = str(mail_replay["steps"][0]["semantic_kind"])
        permission_enforced_by_replay = actual_mail_result_kind == "permission_denied"
        mail_selected_ids = _selected_observation_ids(
            mail_data.get("evidence_snippets") if isinstance(mail_data, Mapping) else ()
        )
        access_binding = kg_eval._access_binding_for_requester(
            str(case.get("requester_user_id", "")),
            kg_index=kg_index,
        )
        retrieval_limit = min(max(int(case.get("limit", 10)), 1), 10)
        kg_retrieval = kg_index.evidence_index.retrieve(
            query_text=query_text,
            limit=retrieval_limit,
            access_binding=access_binding,
            **kg_eval._retrieval_scope(kg_index),
        )
        ontology_retrieval = ontology_index.evidence_index.retrieve(
            query_text=query_text,
            limit=retrieval_limit,
            enable_ontology_rerank=True,
            access_binding=access_binding,
            ontology_revision_id=kg_eval.EVIDENCE_ONTOLOGY_REVISION_ID,
            ontology_signal_vocabulary_hash=(ontology_index.ontology_signal_vocabulary_hash),
            ontology_contract_hash=ontology_index.ontology_contract_hash,
            **kg_eval._retrieval_scope(kg_index),
        )
        kg_selected_ids = kg_retrieval.selected_observation_ids
        ontology_selected_ids = ontology_retrieval.selected_observation_ids
        selected_by_arm = {
            CHATGPT_WITHOUT_FORMOWL: (),
            CHATGPT_WITH_MAIL_EVIDENCE: mail_selected_ids,
            CHATGPT_WITH_CANDIDATE_KG: kg_selected_ids,
            CHATGPT_WITH_ONTOLOGY_GUIDED_KG: ontology_selected_ids,
        }
        arm_rows: list[dict[str, Any]] = []
        for arm in MAJOR_ARMS:
            selected_ids = tuple(selected_by_arm[arm])
            permission_denied = permission_enforced_by_replay and arm != CHATGPT_WITHOUT_FORMOWL
            prediction_result_kind = _prediction_result_kind(
                arm=arm,
                selected_ids=selected_ids,
                mail_result_kind=actual_mail_result_kind,
                permission_denied=permission_denied,
            )
            prediction = build_prediction_from_evidence(
                case_id=case_id,
                result_kind=prediction_result_kind,
                query_text=query_text,
                documents=_evidence_documents(bundle, corpus_root, selected_ids),
                permission_denied=permission_denied,
            )
            score = score_structured_answer(gold, prediction)
            prediction_payload = to_plain(prediction)
            score_payload = score.to_dict()
            arm_without_hash = {
                "arm": arm,
                "prediction_result_kind": prediction_result_kind,
                "selected_evidence_ids": list(selected_ids),
                "selected_evidence_hash": sha256_json(selected_ids),
                "prediction": prediction_payload,
                "prediction_hash": sha256_json(prediction_payload),
                "score": score_payload,
                "score_hash": sha256_json(score_payload),
            }
            arm_rows.append({**arm_without_hash, "arm_result_hash": sha256_json(arm_without_hash)})
        gold_payload = gold.to_dict()
        row_without_hash = {
            "case_manifest_entry_hash": fingerprint,
            "case_id": case_id,
            "result_kind": result_kind,
            "mail_actual_result_kind": actual_mail_result_kind,
            "mail_result_kind_match": actual_mail_result_kind == result_kind,
            "required_source_observation_ids": list(required_ids),
            "gold": gold_payload,
            "gold_hash": sha256_json(gold_payload),
            "kg_retrieval_result_hash": _candidate_retrieval_result_hash(kg_retrieval),
            "ontology_retrieval_result_hash": _candidate_retrieval_result_hash(ontology_retrieval),
            "arm_results": arm_rows,
        }
        rows.append({**row_without_hash, "row_hash": sha256_json(row_without_hash)})
    return {
        "evaluation_type": "reviewer_case_bound_evidence_derived_answer_support",
        "unique_evidence_case_count": len(rows),
        "rows_root_hash": sha256_json([row["row_hash"] for row in rows]),
        "arm_aggregates": _aggregate_grounded_answer_rows(rows),
        "rows": rows,
    }


def _candidate_retrieval_result_hash(retrieval: Any) -> str:
    return sha256_json(
        {
            "plan": to_plain(retrieval.plan),
            "selected_observation_ids": list(retrieval.selected_observation_ids),
            "rejected": retrieval.rejected,
            "rejection_reason": retrieval.rejection_reason,
        }
    )


def _prediction_result_kind(
    *,
    arm: str,
    selected_ids: Sequence[str],
    mail_result_kind: str,
    permission_denied: bool,
) -> str:
    if permission_denied:
        return "permission_denied"
    if arm == CHATGPT_WITH_MAIL_EVIDENCE:
        if mail_result_kind not in RESULT_KINDS:
            raise ContractValidationError("mail replay result kind is unsupported")
        return mail_result_kind
    return "owner_match" if selected_ids else "no_match"


def _public_grounded_answer_summary(
    evaluation: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if evaluation is None:
        return {
            "executed": False,
            "unique_evidence_case_count": 0,
            "rows_root_hash": None,
            "arm_aggregates": [],
        }
    return {
        "executed": True,
        "unique_evidence_case_count": int(evaluation["unique_evidence_case_count"]),
        "rows_root_hash": evaluation["rows_root_hash"],
        "arm_aggregates": evaluation["arm_aggregates"],
    }


def _aggregate_grounded_answer_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    aggregates: list[dict[str, Any]] = []
    for arm in MAJOR_ARMS:
        answer_scores: list[Mapping[str, Any]] = []
        safety_scores: dict[str, list[Mapping[str, Any]]] = {
            "no_match": [],
            "permission_denied": [],
        }
        for row in rows:
            result_kind = str(row["result_kind"])
            arm_result = next(result for result in row["arm_results"] if result["arm"] == arm)
            score = arm_result["score"]
            if result_kind == "owner_match":
                answer_scores.append(score)
            else:
                safety_scores[result_kind].append(score)
        answer_score_sum = sum(
            int(round(float(score["overall_score"]) * 1_000_000)) for score in answer_scores
        )
        aggregate_without_hash = {
            "arm": arm,
            "case_count": len(rows),
            "answer_usefulness": {
                "case_count": len(answer_scores),
                "outcome_correct_count": sum(
                    bool(score["outcome_correct"]) for score in answer_scores
                ),
                "overall_score_micro_sum": answer_score_sum,
                "overall_score_average_micro": _micro_average(
                    answer_score_sum,
                    len(answer_scores),
                ),
                "dimension_micro": _aggregate_structured_dimensions(answer_scores),
            },
            "safety": {
                result_kind: {
                    "case_count": len(scores),
                    "safe_response_count": sum(bool(score["safe_response"]) for score in scores),
                    "safe_response_pass_rate_basis_points": _basis_points(
                        sum(bool(score["safe_response"]) for score in scores),
                        len(scores),
                    ),
                }
                for result_kind, scores in safety_scores.items()
            },
        }
        aggregates.append(
            {
                **aggregate_without_hash,
                "aggregate_hash": sha256_json(aggregate_without_hash),
            }
        )
    return aggregates


def _aggregate_structured_dimensions(
    scores: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"matched": 0, "expected": 0, "predicted": 0, "case_count": 0}
    )
    for score in scores:
        dimensions = score.get("dimensions")
        if not isinstance(dimensions, Mapping):
            continue
        for name, dimension in dimensions.items():
            if not isinstance(dimension, Mapping) or dimension.get("applicable") is not True:
                continue
            total = totals[str(name)]
            total["matched"] += int(dimension.get("matched", 0))
            total["expected"] += int(dimension.get("expected", 0))
            total["predicted"] += int(dimension.get("predicted", 0))
            total["case_count"] += 1
    aggregated: dict[str, dict[str, int]] = {}
    for name, total in sorted(totals.items()):
        precision = total["matched"] / total["predicted"] if total["predicted"] else 1.0
        recall = total["matched"] / total["expected"] if total["expected"] else 1.0
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        aggregated[name] = {
            **total,
            "precision_micro": int(round(precision * 1_000_000)),
            "recall_micro": int(round(recall * 1_000_000)),
            "f1_micro": int(round(f1 * 1_000_000)),
        }
    return aggregated


def _replay_tool_payload(private_replay_row: Mapping[str, Any]) -> Mapping[str, Any]:
    response = private_replay_row.get("response")
    result = response.get("result") if isinstance(response, Mapping) else None
    content = result.get("content") if isinstance(result, Mapping) else None
    first = content[0] if isinstance(content, list) and content else None
    payload = first.get("json") if isinstance(first, Mapping) else None
    return payload if isinstance(payload, Mapping) else {}


def _selected_observation_ids(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        str(item["source_observation_id"])
        for item in value
        if isinstance(item, Mapping) and isinstance(item.get("source_observation_id"), str)
    )


def _evidence_documents(
    bundle: MailEvidenceBundle | None,
    corpus_root: Path,
    evidence_ids: Iterable[str],
) -> tuple[EvidenceDocument, ...]:
    resolved_ids = tuple(evidence_ids)
    if bundle is not None:
        return evidence_documents_from_bundle(bundle, resolved_ids)
    observations_dir = corpus_root / "data" / "ingestion" / "observations"
    documents: list[EvidenceDocument] = []
    for evidence_id in resolved_ids:
        path = observations_dir / f"{evidence_id}.json"
        payload = _read_json(path, "offline_eval_failed")
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise RuntimeError("grounded evidence observation is missing text")
        documents.append(
            EvidenceDocument(
                evidence_id=evidence_id,
                text=text,
                sent_at=(
                    str(payload["created_at"])
                    if isinstance(payload.get("created_at"), str)
                    else None
                ),
            )
        )
    return tuple(documents)


def _expanded_case(
    *,
    case: Mapping[str, Any],
    base_index: int,
    scenario_index: int,
    scenario: Mapping[str, str],
    source_rows: Mapping[str, Mapping[str, Any]],
    structured_scores: Mapping[str, Mapping[str, Any]],
    actual_mail_result_kind: str,
    tools_list_response: Mapping[str, Any],
) -> dict[str, Any]:
    base_fingerprint = str(case["private_fingerprint"])
    scenario_hash = sha256_json({"policy": POLICY_VERSION, **scenario})
    expanded_case_hash = sha256_json(
        {
            "base_case_fingerprint": base_fingerprint,
            "scenario_hash": scenario_hash,
        }
    )
    base_query = str(case["query_text"])
    private_query = _private_user_query(base_query, scenario)
    trajectory = _private_trajectory(
        base_query,
        private_query,
        scenario,
        actual_result_kind=actual_mail_result_kind,
    )
    tool_selection_status, argument_contract_status = _trajectory_contract_statuses(
        trajectory,
        tools_list_response,
    )
    result_kind = str(case["result_kind"])
    arm_results = [
        _simulate_arm(
            arm=arm,
            result_kind=result_kind,
            scenario=scenario,
            scenario_index=scenario_index,
            source_row=source_rows.get(arm),
            structured_score=structured_scores.get(arm),
            tool_selection_status=tool_selection_status,
            argument_contract_status=argument_contract_status,
            trajectory=trajectory,
        )
        for arm in MAJOR_ARMS
    ]
    public_row_without_hash = {
        "expanded_case_hash": expanded_case_hash,
        "base_case_hash": sha256_json(base_fingerprint),
        "scenario_hash": scenario_hash,
        "base_case_ordinal": base_index,
        "scenario_ordinal": scenario_index,
        "result_kind": result_kind,
        "arm_results": arm_results,
    }
    public_row = {
        **public_row_without_hash,
        "row_hash": sha256_json(public_row_without_hash),
    }
    return {
        "public_row": public_row,
        "private_manifest_row": {
            "expanded_case_hash": expanded_case_hash,
            "base_case_id": case.get("case_id"),
            "base_case_private_fingerprint": base_fingerprint,
            "base_case_hash": public_row["base_case_hash"],
            "scenario_hash": scenario_hash,
            "base_case_ordinal": base_index,
            "scenario_ordinal": scenario_index,
            "result_kind": result_kind,
            "actual_mail_result_kind": actual_mail_result_kind,
            "scenario": dict(scenario),
            "user_query": private_query,
            "trajectory": trajectory,
            "tool_selection_status": tool_selection_status,
            "argument_contract_status": argument_contract_status,
        },
        "private_result_row": {
            "expanded_case_hash": expanded_case_hash,
            "base_case_id": case.get("case_id"),
            "base_case_private_fingerprint": base_fingerprint,
            "base_case_hash": public_row["base_case_hash"],
            "scenario_hash": scenario_hash,
            "base_case_ordinal": base_index,
            "scenario_ordinal": scenario_index,
            "result_kind": result_kind,
            "actual_mail_result_kind": actual_mail_result_kind,
            "required_source_observation_ids": list(
                case.get("required_source_observation_ids", [])
            ),
            "forbidden_source_observation_ids": list(
                case.get("forbidden_source_observation_ids", [])
            ),
            "public_row_hash": public_row["row_hash"],
            "arm_results": arm_results,
        },
    }


def _private_user_query(base_query: str, scenario: Mapping[str, str]) -> str:
    urgency = {
        "routine": "This is a routine review.",
        "today": "I need this resolved today.",
        "urgent": "This is urgent.",
        "incident": "Treat this as an active supply-chain incident.",
    }[scenario["urgency"]]
    return (
        f"I am the {scenario['persona'].replace('_', ' ')}. {urgency} "
        f"{base_query} Respond as a {scenario['answer_format'].replace('_', ' ')}."
    )


def _private_trajectory(
    base_query: str,
    private_query: str,
    scenario: Mapping[str, str],
    *,
    actual_result_kind: str,
) -> list[dict[str, Any]]:
    style = scenario["conversation_style"]
    if style == "clarification_then_tool":
        return [
            {"role": "user", "text": private_query},
            {
                "role": "assistant",
                "clarification_request": (
                    "Should I focus on the latest status, blocker ownership, deadline, "
                    "and next action for this procurement question?"
                ),
            },
            {
                "role": "user",
                "clarification_response": "Yes; use governed mail evidence for that scope.",
            },
            {
                "role": "assistant",
                "tool_call": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": base_query,
                        "mail_import_session_id": "bound_from_case_context",
                        "limit": 10,
                    },
                },
            },
            {"role": "tool", "result_dependency": "first_query_result"},
        ]
    turns: list[dict[str, Any]] = [
        {"role": "user", "text": private_query},
        {
            "role": "assistant",
            "tool_call": {
                "name": "query_mail_evidence",
                "arguments": {
                    "query_text": base_query,
                    "mail_import_session_id": "bound_from_case_context",
                    "limit": 10,
                },
            },
        },
        {"role": "tool", "result_dependency": "first_query_result"},
    ]
    if style in {
        "follow_up_refinement",
        "correction_after_no_match",
        "permission_boundary_follow_up",
    }:
        required_result_kind, refinement = {
            "follow_up_refinement": (
                "owner_match",
                "Focus on the latest blocker, owner, deadline, and next action.",
            ),
            "correction_after_no_match": (
                "no_match",
                "Broaden the business terms but keep the same governed session.",
            ),
            "permission_boundary_follow_up": (
                "permission_denied",
                "Retry only within my accessible evidence and explain the permission boundary.",
            ),
        }[style]
        triggered = actual_result_kind == required_result_kind
        turns.append(
            {
                "role": "assistant",
                "trajectory_condition": {
                    "actual_result_kind": actual_result_kind,
                    "required_result_kind": required_result_kind,
                    "triggered": triggered,
                },
            }
        )
        if not triggered:
            return turns
        turns.append(
            {
                "role": "user",
                "text": refinement,
            }
        )
        turns.append(
            {
                "role": "assistant",
                "tool_call": {
                    "name": "query_mail_evidence",
                    "arguments": {
                        "query_text": base_query + " " + refinement,
                        "mail_import_session_id": "bound_from_case_context",
                        "limit": 5 if style != "correction_after_no_match" else 20,
                    },
                    "depends_on": "first_query_result",
                },
            }
        )
    return turns


def _trajectory_contract_statuses(
    trajectory: Sequence[Mapping[str, Any]],
    tools_list_response: Mapping[str, Any],
) -> tuple[str, str]:
    result = tools_list_response.get("result")
    tools = result.get("tools") if isinstance(result, Mapping) else None
    tool_by_name = (
        {
            str(tool.get("name")): tool
            for tool in tools
            if isinstance(tool, Mapping) and isinstance(tool.get("name"), str)
        }
        if isinstance(tools, list)
        else {}
    )
    calls = [
        turn.get("tool_call")
        for turn in trajectory
        if isinstance(turn, Mapping) and isinstance(turn.get("tool_call"), Mapping)
    ]
    if not calls:
        return STATUS_FAILED, STATUS_FAILED
    selection_passed = all(str(call.get("name")) in tool_by_name for call in calls)
    if not selection_passed:
        return STATUS_FAILED, STATUS_FAILED
    arguments_passed = all(
        _schema_matches(
            call.get("arguments"),
            tool_by_name[str(call.get("name"))].get("inputSchema"),
        )
        for call in calls
    )
    return STATUS_PASSED, STATUS_PASSED if arguments_passed else STATUS_FAILED


def _trajectory_tool_calls(trajectory: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        turn["tool_call"]
        for turn in trajectory
        if isinstance(turn, Mapping) and isinstance(turn.get("tool_call"), Mapping)
    ]


def _trajectory_condition(trajectory: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    conditions = [
        turn["trajectory_condition"]
        for turn in trajectory
        if isinstance(turn, Mapping) and isinstance(turn.get("trajectory_condition"), Mapping)
    ]
    return conditions[0] if len(conditions) == 1 else None


def _trajectory_has_clarification(trajectory: Sequence[Mapping[str, Any]]) -> bool:
    return any("clarification_request" in turn for turn in trajectory) and any(
        "clarification_response" in turn for turn in trajectory
    )


def _schema_matches(value: Any, schema: Any) -> bool:
    if not isinstance(schema, Mapping):
        return False
    required_keys = schema.get("required")
    if required_keys is not None:
        if not isinstance(value, Mapping) or not isinstance(required_keys, list):
            return False
        if any(key not in value for key in required_keys):
            return False
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, Mapping):
            return False
        required = schema.get("required", [])
        if not isinstance(required, list) or any(key not in value for key in required):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return False
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        if any(
            key in properties and not _schema_matches(item, properties[key])
            for key, item in value.items()
        ):
            return False
        any_of = schema.get("anyOf")
        if any_of is not None:
            if not isinstance(any_of, list):
                return False
            if sum(_schema_matches(value, option) for option in any_of) != 1:
                return False
    elif schema_type == "string":
        if not isinstance(value, str):
            return False
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            return False
    elif schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            return False
        if isinstance(schema.get("minimum"), int) and value < schema["minimum"]:
            return False
        if isinstance(schema.get("maximum"), int) and value > schema["maximum"]:
            return False
    elif schema_type is not None:
        return False
    if "const" in schema and value != schema["const"]:
        return False
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        return False
    return True


def _simulation_tools_list_response() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "simulation_tools_list",
        "result": {
            "tools": [
                {
                    "name": "query_mail_evidence",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query_text": {"type": "string", "minLength": 1},
                            "mail_import_session_id": {"type": "string", "minLength": 1},
                            "mail_evidence_bundle_id": {"type": "string", "minLength": 1},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                        },
                        "required": ["query_text"],
                        "anyOf": [
                            {"required": ["mail_import_session_id"]},
                            {"required": ["mail_evidence_bundle_id"]},
                        ],
                        "additionalProperties": False,
                    },
                }
            ]
        },
    }


def _simulate_arm(
    *,
    arm: str,
    result_kind: str,
    scenario: Mapping[str, str],
    scenario_index: int,
    source_row: Mapping[str, Any] | None,
    structured_score: Mapping[str, Any] | None,
    tool_selection_status: str,
    argument_contract_status: str,
    trajectory: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    uses_tool = arm != CHATGPT_WITHOUT_FORMOWL
    source_passed = _source_status(arm, source_row) == STATUS_PASSED
    safety_applicable = result_kind in {"no_match", "permission_denied"}
    positive = result_kind == "owner_match"

    tool_selection = tool_selection_status if uses_tool else STATUS_NOT_APPLICABLE
    argument_contract = argument_contract_status if uses_tool else STATUS_NOT_APPLICABLE
    retrieval = (
        STATUS_PASSED
        if uses_tool and source_passed
        else STATUS_FAILED
        if uses_tool
        else STATUS_NOT_APPLICABLE
    )
    safety = _structured_safety_status(
        safety_applicable=safety_applicable,
        structured_score=structured_score,
    )
    final_answer = _structured_final_answer_status(
        positive=positive,
        structured_score=structured_score,
    )
    citation = _structured_dimension_status(
        positive=positive,
        structured_score=structured_score,
        dimension_names=("citations",),
    )
    actionability = _structured_dimension_status(
        positive=positive,
        structured_score=structured_score,
        dimension_names=(
            "open_blockers",
            "responsible_parties",
            "deadlines",
            "deadline_disclosure",
            "next_actions",
            "action_links",
            "dependencies",
            "uncertainties",
        ),
    )
    applicable = [
        tool_selection,
        argument_contract,
        retrieval,
        final_answer,
        citation,
        actionability,
        safety,
    ]
    overall = (
        STATUS_PASSED
        if positive
        and structured_score is not None
        and all(status in {STATUS_PASSED, STATUS_NOT_APPLICABLE} for status in applicable)
        else STATUS_FAILED
        if positive and structured_score is not None
        else STATUS_NOT_APPLICABLE
    )
    tool_call_count = 0 if not uses_tool else len(_trajectory_tool_calls(trajectory))
    trajectory_turn_count = len(trajectory)
    simulated_cost_ms = _simulated_cost_ms(
        arm=arm,
        source_row=source_row,
        scenario_index=scenario_index,
        tool_call_count=tool_call_count,
        trajectory_turn_count=trajectory_turn_count,
    )
    contract_hash = sha256_json(
        {
            "tool": "none" if not uses_tool else "query_mail_evidence",
            "argument_contract": (
                [] if not uses_tool else ["query_text", "mail_import_session_id", "limit"]
            ),
            "conversation_style": scenario["conversation_style"],
        }
    )
    result_without_hash = {
        "arm": arm,
        "overall_status": overall,
        "tool_selection_status": tool_selection,
        "argument_contract_status": argument_contract,
        "retrieval_status": retrieval,
        "final_answer_status": final_answer,
        "citation_status": citation,
        "actionability_status": actionability,
        "no_match_permission_safety_status": safety,
        "structured_answer_score_hash": (
            sha256_json(structured_score) if structured_score is not None else None
        ),
        "structured_answer_overall_score_micro": _structured_score_micro(structured_score),
        "tool_call_count": tool_call_count,
        "trajectory_turn_count": trajectory_turn_count,
        "simulated_cost_ms": simulated_cost_ms,
        "argument_contract_hash": contract_hash,
        "source_status_hash": sha256_json(
            {
                "arm": arm,
                "source_status": _source_status(arm, source_row),
                "source_row_hash": sha256_json(source_row) if source_row is not None else None,
            }
        ),
    }
    return {**result_without_hash, "result_hash": sha256_json(result_without_hash)}


def _grounded_arm_scores_by_fingerprint(
    evaluation: Mapping[str, Any] | None,
) -> dict[str, dict[str, Mapping[str, Any]]]:
    if evaluation is None:
        return {}
    rows = evaluation.get("rows")
    if not isinstance(rows, list):
        raise ValueError("grounded answer rows are missing")
    scores: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("grounded answer row is invalid")
        fingerprint = str(row.get("case_manifest_entry_hash", ""))
        arm_results = row.get("arm_results")
        if not fingerprint or not isinstance(arm_results, list) or fingerprint in scores:
            raise ValueError("grounded answer row binding is invalid")
        by_arm: dict[str, Mapping[str, Any]] = {}
        for arm_result in arm_results:
            if not isinstance(arm_result, Mapping):
                raise ValueError("grounded answer arm result is invalid")
            arm = str(arm_result.get("arm", ""))
            score = arm_result.get("score")
            if arm not in MAJOR_ARMS or not isinstance(score, Mapping) or arm in by_arm:
                raise ValueError("grounded answer score binding is invalid")
            by_arm[arm] = score
        if set(by_arm) != set(MAJOR_ARMS):
            raise ValueError("grounded answer arm set is incomplete")
        scores[fingerprint] = by_arm
    return scores


def _structured_final_answer_status(
    *,
    positive: bool,
    structured_score: Mapping[str, Any] | None,
) -> str:
    if not positive:
        return STATUS_NOT_APPLICABLE
    if structured_score is None:
        return STATUS_NOT_APPLICABLE
    return (
        STATUS_PASSED
        if structured_score.get("outcome_correct") is True
        and float(structured_score.get("overall_score", 0.0)) == 1.0
        else STATUS_FAILED
    )


def _structured_dimension_status(
    *,
    positive: bool,
    structured_score: Mapping[str, Any] | None,
    dimension_names: Sequence[str],
) -> str:
    if not positive or structured_score is None:
        return STATUS_NOT_APPLICABLE
    dimensions = structured_score.get("dimensions")
    if not isinstance(dimensions, Mapping):
        return STATUS_FAILED
    applicable = []
    for name in dimension_names:
        dimension = dimensions.get(name)
        if not isinstance(dimension, Mapping):
            return STATUS_FAILED
        if dimension.get("applicable") is True:
            applicable.append(dimension)
    if not applicable:
        return STATUS_FAILED
    return (
        STATUS_PASSED
        if all(float(dimension.get("f1", 0.0)) == 1.0 for dimension in applicable)
        else STATUS_FAILED
    )


def _structured_safety_status(
    *,
    safety_applicable: bool,
    structured_score: Mapping[str, Any] | None,
) -> str:
    if not safety_applicable or structured_score is None:
        return STATUS_NOT_APPLICABLE
    return STATUS_PASSED if structured_score.get("safe_response") is True else STATUS_FAILED


def _structured_score_micro(structured_score: Mapping[str, Any] | None) -> int | None:
    if structured_score is None:
        return None
    return int(round(float(structured_score.get("overall_score", 0.0)) * 1_000_000))


def _source_status(arm: str, row: Mapping[str, Any] | None) -> str:
    if arm == CHATGPT_WITHOUT_FORMOWL:
        return "no_tool"
    if row is None:
        return STATUS_FAILED
    status_key = {
        CHATGPT_WITH_MAIL_EVIDENCE: "status",
        CHATGPT_WITH_CANDIDATE_KG: "kg_status",
        CHATGPT_WITH_ONTOLOGY_GUIDED_KG: "ontology_status",
    }[arm]
    return str(row.get(status_key, STATUS_FAILED))


def _simulated_cost_ms(
    *,
    arm: str,
    source_row: Mapping[str, Any] | None,
    scenario_index: int,
    tool_call_count: int,
    trajectory_turn_count: int,
) -> int:
    if arm == CHATGPT_WITHOUT_FORMOWL:
        source_elapsed = 0
    else:
        key = {
            CHATGPT_WITH_MAIL_EVIDENCE: "elapsed_ms",
            CHATGPT_WITH_CANDIDATE_KG: "elapsed_ms",
            CHATGPT_WITH_ONTOLOGY_GUIDED_KG: "ontology_elapsed_ms",
        }[arm]
        value = source_row.get(key) if source_row is not None else 0
        source_elapsed = value if isinstance(value, int) and not isinstance(value, bool) else 0
    return (
        20 + source_elapsed + tool_call_count * 7 + trajectory_turn_count * 3 + scenario_index % 11
    )


def _aggregate_arm_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        for result in row["arm_results"]:
            grouped[str(result["arm"])].append(result)
    return [_aggregate_one_arm(arm, grouped[arm]) for arm in MAJOR_ARMS]


def _aggregate_one_arm(
    arm: str,
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    metric_keys = (
        "overall_status",
        "tool_selection_status",
        "argument_contract_status",
        "retrieval_status",
        "final_answer_status",
        "citation_status",
        "actionability_status",
        "no_match_permission_safety_status",
    )
    status_aggregates: dict[str, Any] = {}
    for key in metric_keys:
        counts = Counter(str(result[key]) for result in results)
        applicable = len(results) - counts[STATUS_NOT_APPLICABLE]
        passed = counts[STATUS_PASSED]
        status_aggregates[key.removesuffix("_status")] = {
            "passed_count": passed,
            "failed_count": counts[STATUS_FAILED],
            "not_applicable_count": counts[STATUS_NOT_APPLICABLE],
            "applicable_count": applicable,
            "pass_rate_basis_points": _basis_points(passed, applicable),
        }
    cost_values = sorted(int(result["simulated_cost_ms"]) for result in results)
    total_cost = sum(cost_values)
    total_tool_calls = sum(int(result["tool_call_count"]) for result in results)
    total_trajectory_turns = sum(int(result["trajectory_turn_count"]) for result in results)
    aggregate_without_hash = {
        "arm": arm,
        "case_count": len(results),
        "status_aggregates": status_aggregates,
        "tool_call_count_total": total_tool_calls,
        "tool_call_count_average_milli": _milli_average(total_tool_calls, len(results)),
        "trajectory_turn_count_total": total_trajectory_turns,
        "trajectory_turn_count_average_milli": _milli_average(
            total_trajectory_turns,
            len(results),
        ),
        "simulated_cost_ms_total": total_cost,
        "simulated_cost_ms_average_milli": _milli_average(total_cost, len(results)),
        "simulated_cost_ms_min": cost_values[0] if cost_values else 0,
        "simulated_cost_ms_median": cost_values[len(cost_values) // 2] if cost_values else 0,
        "simulated_cost_ms_max": cost_values[-1] if cost_values else 0,
        "unique_result_hash_count": len({str(result["result_hash"]) for result in results}),
    }
    return {
        **aggregate_without_hash,
        "aggregate_hash": sha256_json(aggregate_without_hash),
    }


def _factorial_summary(
    report: Mapping[str, Any],
    *,
    scenario_multiplier: int,
    major_arm_aggregates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summaries = _factorial_summaries(report)
    ranked = sorted(
        summaries,
        key=lambda item: (
            int(item["passed_case_count"]),
            -int(item["operator_count"]),
            -int(item["elapsed_ms"]),
            str(item["arm_id_hash"]),
        ),
    )
    worst = ranked[0]
    median = ranked[len(ranked) // 2]
    best = ranked[-1]
    major_base_passed = {
        aggregate["arm"]: int(
            aggregate["status_aggregates"]["retrieval"]["passed_count"] / scenario_multiplier
        )
        for aggregate in major_arm_aggregates
        if aggregate["arm"] != CHATGPT_WITHOUT_FORMOWL
    }
    return {
        "arm_count": len(summaries),
        "arm_summary_hash": sha256_json(summaries),
        "comparison_basis": "retrieval_passed_case_count",
        "major_arm_status_key": "retrieval_status",
        "per_case_factorial_rows_available": False,
        "per_case_factorial_rows_synthesized": False,
        "best": _factorial_snapshot(best, scenario_multiplier),
        "median": _factorial_snapshot(median, scenario_multiplier),
        "worst": _factorial_snapshot(worst, scenario_multiplier),
        "best_retrieval_delta_vs_major_arms_base_case_count": {
            arm: int(best["passed_case_count"]) - passed
            for arm, passed in sorted(major_base_passed.items())
        },
        "best_retrieval_delta_vs_major_arms_expanded_case_count": {
            arm: (int(best["passed_case_count"]) - passed) * scenario_multiplier
            for arm, passed in sorted(major_base_passed.items())
        },
        "retrieval_arms_better_than_candidate_kg_count": sum(
            1
            for item in summaries
            if int(item["passed_case_count"]) > major_base_passed.get(CHATGPT_WITH_CANDIDATE_KG, 0)
        ),
        "retrieval_arms_equal_to_candidate_kg_count": sum(
            1
            for item in summaries
            if int(item["passed_case_count"]) == major_base_passed.get(CHATGPT_WITH_CANDIDATE_KG, 0)
        ),
        "retrieval_arms_worse_than_candidate_kg_count": sum(
            1
            for item in summaries
            if int(item["passed_case_count"]) < major_base_passed.get(CHATGPT_WITH_CANDIDATE_KG, 0)
        ),
    }


def _factorial_snapshot(
    summary: Mapping[str, Any],
    scenario_multiplier: int,
) -> dict[str, Any]:
    return {
        "arm_id_hash": summary["arm_id_hash"],
        "operator_order": list(summary["operator_order"]),
        "operator_count": int(summary["operator_count"]),
        "base_passed_case_count": int(summary["passed_case_count"]),
        "projected_expanded_passed_case_count": int(summary["passed_case_count"])
        * scenario_multiplier,
        "pass_rate_basis_points": int(summary["pass_rate_basis_points"]),
        "source_measured_elapsed_ms": int(summary["elapsed_ms"]),
        "arm_summary_hash": summary["arm_summary_hash"],
    }


def validate_report(
    report: Any,
    *,
    private_manifest_payload: Mapping[str, Any] | None = None,
    private_rows_payload: Mapping[str, Any] | None = None,
    sources: SourceBundle | None = None,
    private_dir: Path | None = None,
    expected_replay_attestation_hash: str | None = None,
    expected_grounded_answer_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, Mapping):
        return _validation(False, ["report must be an object"])
    if report.get("report_type") != REPORT_TYPE:
        blockers.append("report_type mismatch")
    metrics = _mapping(report.get("metrics"), "metrics", blockers)
    safe = _mapping(report.get("safe_outputs"), "safe_outputs", blockers)
    claim_boundary = _mapping(report.get("claim_boundary"), "claim_boundary", blockers)
    if "blocked_reason" in metrics:
        _validate_blocked(metrics, safe, claim_boundary, blockers)
    else:
        _validate_success(
            report,
            metrics,
            safe,
            claim_boundary,
            blockers,
            private_manifest_payload=private_manifest_payload,
            private_rows_payload=private_rows_payload,
            sources=sources,
            private_dir=private_dir,
            expected_replay_attestation_hash=expected_replay_attestation_hash,
            expected_grounded_answer_evaluation=expected_grounded_answer_evaluation,
        )
    _reject_forbidden_public_fields(report, blockers)
    try:
        assert_no_public_raw_references(_without_validation(report), "chatgpt_mcp_eval_report")
    except Exception:
        blockers.append("public output raw leak guard failed")
    return _validation(not blockers, blockers)


def _validate_success(
    report: Mapping[str, Any],
    metrics: Mapping[str, Any],
    safe: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
    *,
    private_manifest_payload: Mapping[str, Any] | None,
    private_rows_payload: Mapping[str, Any] | None,
    sources: SourceBundle | None,
    private_dir: Path | None,
    expected_replay_attestation_hash: str | None,
    expected_grounded_answer_evaluation: Mapping[str, Any] | None,
) -> None:
    required_true_metrics = {
        "source_private_manifest_loaded",
        "source_reports_loaded",
        "source_reports_bound_to_same_manifest",
        "source_report_validators_recomputed",
        "source_case_status_hash_rows_bound",
        "answer_quality_derived_only_from_structured_oracle",
        "answer_usefulness_and_safety_aggregated_separately",
        "deterministic_expansion_generated",
        "scenario_product_exact",
        "private_manifest_written",
        "private_rows_written",
        "private_files_mode_0600",
        "private_atomic_transaction_completed",
        "public_report_excludes_private_query_and_ids",
        "factorial_326_arms_integrated_at_aggregate_only",
        "factorial_per_case_rows_not_claimed",
        "model_free_simulation_disclosed",
        "live_chatgpt_quality_not_claimed",
        "row_derived_validation_recomputed",
        "full_private_source_binding_validated",
        "public_report_bounded_to_5_mib",
        "raw_leak_guard_passed",
        "offline_eval_completed",
    }
    for key in required_true_metrics:
        if metrics.get(key) is not True:
            blockers.append(f"required metric is not true: {key}")
    if type(metrics.get("production_case_count_is_50000")) is not bool:
        blockers.append("production_case_count_is_50000 must be boolean")

    if "public_rows" in safe:
        blockers.append("safe_outputs.public_rows must be omitted")
    base_count = _integer(safe.get("base_case_count"))
    unique_evidence_count = _integer(safe.get("unique_evidence_case_count"))
    scenario_count = _integer(safe.get("scenario_count_per_base_case"))
    expanded_count = _integer(safe.get("expanded_case_count"))
    rendered_scenario_count = _integer(safe.get("rendered_scenario_count"))
    if unique_evidence_count != base_count:
        blockers.append("unique evidence case count must equal base case count")
    if rendered_scenario_count != expanded_count:
        blockers.append("rendered scenario count must equal expanded case count")
    if safe.get("rendered_scenarios_are_not_independent_evidence_cases") is not True:
        blockers.append("rendered scenarios must not be claimed as independent evidence")
    if base_count * scenario_count != expanded_count:
        blockers.append("expanded_case_count does not match base/scenario product")

    dimension_summary = _mapping(
        safe.get("dimension_summary"),
        "safe_outputs.dimension_summary",
        blockers,
    )
    dimension_product = (
        _integer(dimension_summary.get("persona_count"))
        * _integer(dimension_summary.get("urgency_count"))
        * _integer(dimension_summary.get("answer_format_count"))
        * _integer(dimension_summary.get("conversation_style_count"))
    )
    if dimension_summary.get("scenario_product") != dimension_product:
        blockers.append("dimension scenario product mismatch")
    if scenario_count != dimension_product:
        blockers.append("scenario_count_per_base_case does not match dimensions")

    rows = _validate_private_source_binding(
        safe,
        blockers,
        private_manifest_payload=private_manifest_payload,
        private_rows_payload=private_rows_payload,
        sources=sources,
        private_dir=private_dir,
    )
    _validate_stateful_trajectory_summary(
        safe,
        private_manifest_payload=private_manifest_payload,
        private_rows_payload=private_rows_payload,
        blockers=blockers,
    )
    _validate_grounded_mcp_replay(
        safe,
        metrics,
        private_rows_payload=private_rows_payload,
        expected_unique_evidence_count=unique_evidence_count,
        expected_replay_attestation_hash=expected_replay_attestation_hash,
        blockers=blockers,
    )
    _validate_grounded_answer_evaluation(
        safe,
        metrics,
        private_rows_payload=private_rows_payload,
        expected_unique_evidence_count=unique_evidence_count,
        expected_grounded_answer_evaluation=expected_grounded_answer_evaluation,
        blockers=blockers,
    )
    expected_unique = len({row.get("expanded_case_hash") for row in rows})
    if safe.get("unique_expanded_case_hash_count") != expected_unique:
        blockers.append("unique expanded case hash count mismatch")
    if expected_unique != len(rows):
        blockers.append("expanded case hashes must be unique")
    if len(rows) != expanded_count:
        blockers.append("private row count does not match expanded_case_count")

    expected_result_counts = dict(
        sorted(Counter(str(row.get("result_kind")) for row in rows).items())
    )
    if safe.get("result_kind_counts") != expected_result_counts:
        blockers.append("result kind counts do not match public rows")
    expected_aggregates = _aggregate_arm_rows(rows) if rows else []
    if safe.get("arm_aggregates") != expected_aggregates:
        blockers.append("arm aggregates do not match public rows")
    sizes = _mapping(
        safe.get("serialized_sizes_bytes"),
        "safe_outputs.serialized_sizes_bytes",
        blockers,
    )
    for key in ("private_manifest", "private_rows", "public_report_without_validation"):
        if _integer(sizes.get(key)) <= 0:
            blockers.append(f"serialized size must be positive: {key}")
    if sizes.get("public_report_without_validation") != _serialized_json_size(
        _without_validation(report), compact=True
    ):
        blockers.append("public report serialized size mismatch")
    if _serialized_json_size(report, compact=True) > MAX_PUBLIC_REPORT_BYTES:
        blockers.append("public report exceeds 5 MiB")
    performance = _mapping(
        safe.get("measured_performance"),
        "safe_outputs.measured_performance",
        blockers,
    )
    if _integer(performance.get("wall_time_ms")) < 0:
        blockers.append("measured wall time must be non-negative")
    if _integer(performance.get("peak_rss_bytes")) <= 0:
        blockers.append("measured peak RSS must be positive")
    factorial = _mapping(
        safe.get("factorial_aggregate_summary"),
        "safe_outputs.factorial_aggregate_summary",
        blockers,
    )
    if factorial.get("arm_count") != EXPECTED_FACTORIAL_ARM_COUNT:
        blockers.append("factorial arm count must be 326")
    if factorial.get("per_case_factorial_rows_available") is not False:
        blockers.append("factorial per-case availability must be false")
    if factorial.get("per_case_factorial_rows_synthesized") is not False:
        blockers.append("factorial per-case rows must not be synthesized")
    if factorial.get("comparison_basis") != "retrieval_passed_case_count":
        blockers.append("factorial comparison basis must be retrieval")
    if factorial.get("major_arm_status_key") != "retrieval_status":
        blockers.append("factorial major-arm status key must be retrieval_status")
    for forbidden_key in (
        "best_delta_vs_major_arms_base_case_count",
        "best_delta_vs_major_arms_expanded_case_count",
        "arms_better_than_candidate_kg_count",
        "arms_equal_to_candidate_kg_count",
        "arms_worse_than_candidate_kg_count",
    ):
        if forbidden_key in factorial:
            blockers.append("factorial comparison fields must be retrieval-qualified")
    comparison_count = sum(
        _integer(factorial.get(key))
        for key in (
            "retrieval_arms_better_than_candidate_kg_count",
            "retrieval_arms_equal_to_candidate_kg_count",
            "retrieval_arms_worse_than_candidate_kg_count",
        )
    )
    if comparison_count != EXPECTED_FACTORIAL_ARM_COUNT:
        blockers.append("factorial comparison counts must sum to 326")
    case_progress = _mapping(
        safe.get("mail_case_progress_tool_assessment"),
        "safe_outputs.mail_case_progress_tool_assessment",
        blockers,
    )
    if case_progress.get("status") != "blocked_not_case_scoped":
        blockers.append("mail case-progress tool must remain explicitly blocked")
    if case_progress.get("evaluated_as_answer_arm") is not False:
        blockers.append("mail case-progress tool must not be scored as a case arm")
    if not _is_sha256(case_progress.get("reason_hash")):
        blockers.append("mail case-progress blocked reason hash must be sha256")
    _validate_claim_boundary(
        claim_boundary,
        supported=True,
        supports_grounded_replay=bool(
            _mapping(
                safe.get("grounded_mcp_replay"),
                "safe_outputs.grounded_mcp_replay",
                blockers,
            ).get("executed")
        ),
        blockers=blockers,
    )


def _validate_grounded_mcp_replay(
    safe: Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    private_rows_payload: Mapping[str, Any] | None,
    expected_unique_evidence_count: int,
    expected_replay_attestation_hash: str | None,
    blockers: list[str],
) -> None:
    public_summary = _mapping(
        safe.get("grounded_mcp_replay"),
        "safe_outputs.grounded_mcp_replay",
        blockers,
    )
    required = expected_unique_evidence_count == PRODUCTION_BASE_CASE_COUNT
    if metrics.get("real_mcp_jsonrpc_replay_completed") is not required:
        blockers.append("real MCP replay completion metric mismatch")
    if public_summary.get("executed") is not required:
        blockers.append("grounded MCP replay execution claim mismatch")
    if public_summary.get("mode") not in {
        "not_run",
        "executed_live_in_process",
        "repaired_live_in_process",
        "validated_private_replay",
    }:
        blockers.append("grounded MCP replay mode is invalid")
    if not required:
        return
    private_replay = (
        private_rows_payload.get("mcp_replay")
        if isinstance(private_rows_payload, Mapping)
        else None
    )
    if not isinstance(private_replay, Mapping):
        blockers.append("private MCP replay artifact is required")
        return
    try:
        artifact = ReplayArtifact(
            unique_evidence_case_count=_integer(private_replay.get("unique_evidence_case_count")),
            tools_list_response=dict(private_replay.get("tools_list_response", {})),
            tools_list_response_hash=str(private_replay.get("tools_list_response_hash", "")),
            public_rows=tuple(private_replay.get("public_rows", ())),
            private_rows=tuple(private_replay.get("private_rows", ())),
            public_rows_root_hash=str(private_replay.get("public_rows_root_hash", "")),
            private_rows_root_hash=str(private_replay.get("private_rows_root_hash", "")),
            attestation_hash=str(private_replay.get("attestation_hash", "")),
        )
        if expected_replay_attestation_hash is None:
            raise ContractValidationError("external replay trust anchor is required")
        validate_replay_artifact(
            artifact,
            expected_attestation_hash=expected_replay_attestation_hash,
        )
    except (ContractValidationError, TypeError, ValueError):
        blockers.append("private MCP replay artifact validation failed")
        return
    expected_summary = _public_replay_summary(
        artifact,
        mode=str(public_summary.get("mode")),
        repair_summary=(
            private_rows_payload.get("replay_repair_summary")
            if isinstance(private_rows_payload.get("replay_repair_summary"), Mapping)
            else None
        ),
    )
    if public_summary != expected_summary:
        blockers.append("public MCP replay summary binding mismatch")


def _validate_stateful_trajectory_summary(
    safe: Mapping[str, Any],
    *,
    private_manifest_payload: Mapping[str, Any] | None,
    private_rows_payload: Mapping[str, Any] | None,
    blockers: list[str],
) -> None:
    summary = _mapping(
        safe.get("stateful_trajectory_summary"),
        "safe_outputs.stateful_trajectory_summary",
        blockers,
    )
    if summary.get("rendered_variants_only") is not True:
        blockers.append("rendered stateful variants must be labeled rendered-only")
    if summary.get("unique_evidence_case_template_count") != safe.get("unique_evidence_case_count"):
        blockers.append("stateful unique evidence template count mismatch")
    cases = (
        private_manifest_payload.get("cases")
        if isinstance(private_manifest_payload, Mapping)
        else None
    )
    if not isinstance(cases, list):
        blockers.append("private trajectory cases are required")
        return
    valid_cases = [row for row in cases if isinstance(row, Mapping)]
    trajectories = [row.get("trajectory") for row in valid_cases]
    if any(not isinstance(trajectory, list) for trajectory in trajectories):
        blockers.append("stateful trajectories must be lists")
        return
    style_counts = dict(
        sorted(
            Counter(
                str(row.get("scenario", {}).get("conversation_style"))
                for row in valid_cases
                if isinstance(row.get("scenario"), Mapping)
            ).items()
        )
    )
    if summary.get("conversation_style_counts") != style_counts:
        blockers.append("conversation style counts mismatch")
    triggered_count = sum(
        len(_trajectory_tool_calls(trajectory)) > 1 for trajectory in trajectories
    )
    if summary.get("rendered_response_conditioned_follow_up_scenario_count") != triggered_count:
        blockers.append("response-conditioned follow-up count mismatch")
    not_triggered_count = sum(
        _trajectory_condition(trajectory) is not None
        and _trajectory_condition(trajectory).get("triggered") is False
        for trajectory in trajectories
    )
    if summary.get("rendered_condition_not_triggered_scenario_count") != not_triggered_count:
        blockers.append("non-triggered trajectory condition count mismatch")
    clarification_count = sum(_trajectory_has_clarification(item) for item in trajectories)
    if summary.get("rendered_clarification_exchange_scenario_count") != clarification_count:
        blockers.append("clarification exchange count mismatch")
    tool_contract_count = sum(
        row.get("tool_selection_status") == STATUS_PASSED
        and row.get("argument_contract_status") == STATUS_PASSED
        for row in valid_cases
    )
    if summary.get("rendered_tool_contract_passed_scenario_count") != tool_contract_count:
        blockers.append("rendered tool contract count mismatch")
    condition_counts = dict(
        sorted(
            Counter(
                (
                    f"{condition.get('required_result_kind')}<-"
                    f"{condition.get('actual_result_kind')}:"
                    f"{'triggered' if condition.get('triggered') else 'not_triggered'}"
                )
                for trajectory in trajectories
                if (condition := _trajectory_condition(trajectory)) is not None
            ).items()
        )
    )
    if summary.get("condition_outcome_counts") != condition_counts:
        blockers.append("trajectory condition outcome counts mismatch")
    if summary.get("trajectory_root_hash") != sha256_json(
        [row.get("trajectory") for row in cases if isinstance(row, Mapping)]
    ):
        blockers.append("stateful trajectory root hash mismatch")
    private_replay = (
        private_rows_payload.get("mcp_replay")
        if isinstance(private_rows_payload, Mapping)
        else None
    )
    replay_rows = private_replay.get("public_rows") if isinstance(private_replay, Mapping) else None
    if not isinstance(replay_rows, list):
        expected_executed = 0
        executed_roots: list[Any] = []
    else:
        executed = [
            row
            for row in replay_rows
            if isinstance(row, Mapping) and _integer(row.get("step_count")) > 1
        ]
        expected_executed = len(executed)
        executed_roots = [row.get("trajectory_root_hash") for row in executed]
    if summary.get("executed_unique_case_follow_up_count") != expected_executed:
        blockers.append("executed stateful follow-up count mismatch")
    if expected_executed:
        if summary.get("executed_follow_ups_are_response_derived") is not True:
            blockers.append("executed follow-ups must be response-derived")
        if summary.get("executed_follow_ups_use_same_bound_session") is not True:
            blockers.append("executed follow-ups must use the same bound session")
        if summary.get("executed_follow_up_trajectory_root_hash") != sha256_json(executed_roots):
            blockers.append("executed follow-up trajectory root mismatch")
    if safe.get("unique_evidence_case_count") == PRODUCTION_BASE_CASE_COUNT:
        if expected_executed != len(RESULT_KINDS):
            blockers.append("production replay must execute one follow-up per result kind")


def _validate_grounded_answer_evaluation(
    safe: Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    private_rows_payload: Mapping[str, Any] | None,
    expected_unique_evidence_count: int,
    expected_grounded_answer_evaluation: Mapping[str, Any] | None,
    blockers: list[str],
) -> None:
    public_summary = _mapping(
        safe.get("grounded_answer_evaluation"),
        "safe_outputs.grounded_answer_evaluation",
        blockers,
    )
    required = expected_unique_evidence_count == PRODUCTION_BASE_CASE_COUNT
    if metrics.get("grounded_structured_answer_scoring_completed") is not required:
        blockers.append("grounded structured-answer completion metric mismatch")
    if public_summary.get("executed") is not required:
        blockers.append("grounded structured-answer execution claim mismatch")
    if not required:
        return
    evaluation = (
        private_rows_payload.get("grounded_answer_evaluation")
        if isinstance(private_rows_payload, Mapping)
        else None
    )
    if not isinstance(evaluation, Mapping):
        blockers.append("private grounded answer evaluation is required")
        return
    if expected_grounded_answer_evaluation is None:
        blockers.append("source-rebuilt grounded answer evaluation is required")
    elif evaluation != expected_grounded_answer_evaluation:
        blockers.append("grounded answer evaluation does not match source rebuild")
    rows = evaluation.get("rows")
    if not isinstance(rows, list) or len(rows) != expected_unique_evidence_count:
        blockers.append("private grounded answer rows are invalid")
        return
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            blockers.append(f"grounded answer row {index} must be an object")
            continue
        row_without_hash = dict(row)
        row_hash = row_without_hash.pop("row_hash", None)
        if row_hash != sha256_json(row_without_hash):
            blockers.append(f"grounded answer row {index} hash mismatch")
        try:
            gold = PrivateStructuredAnswerGold.from_dict(row["gold"])
        except (ContractValidationError, KeyError, TypeError):
            blockers.append(f"grounded answer row {index} gold is invalid")
            continue
        if row.get("gold_hash") != sha256_json(gold.to_dict()):
            blockers.append(f"grounded answer row {index} gold hash mismatch")
        arm_results = row.get("arm_results")
        if not isinstance(arm_results, list) or [
            result.get("arm") for result in arm_results if isinstance(result, Mapping)
        ] != list(MAJOR_ARMS):
            blockers.append(f"grounded answer row {index} arm order mismatch")
            continue
        for arm_result in arm_results:
            if not isinstance(arm_result, Mapping):
                blockers.append(f"grounded answer row {index} arm result is invalid")
                continue
            arm_without_hash = dict(arm_result)
            arm_hash = arm_without_hash.pop("arm_result_hash", None)
            if arm_hash != sha256_json(arm_without_hash):
                blockers.append(f"grounded answer row {index} arm hash mismatch")
            try:
                prediction = StructuredAnswerPrediction.from_dict(arm_result["prediction"])
                expected_score = score_structured_answer(gold, prediction).to_dict()
            except (ContractValidationError, KeyError, TypeError):
                blockers.append(f"grounded answer row {index} prediction is invalid")
                continue
            if arm_result.get("prediction_hash") != sha256_json(to_plain(prediction)):
                blockers.append(f"grounded answer row {index} prediction hash mismatch")
            if arm_result.get("score") != expected_score:
                blockers.append(f"grounded answer row {index} score mismatch")
            if arm_result.get("score_hash") != sha256_json(expected_score):
                blockers.append(f"grounded answer row {index} score hash mismatch")
    if evaluation.get("rows_root_hash") != sha256_json(
        [row.get("row_hash") for row in rows if isinstance(row, Mapping)]
    ):
        blockers.append("grounded answer rows root hash mismatch")
    expected_aggregates = _aggregate_grounded_answer_rows(rows)
    for aggregate in expected_aggregates:
        usefulness = aggregate.get("answer_usefulness", {})
        average_micro = usefulness.get("overall_score_average_micro")
        if not isinstance(average_micro, int) or not 0 <= average_micro <= 1_000_000:
            blockers.append("grounded answer average score must be micro-scaled")
        dimensions = usefulness.get("dimension_micro")
        if isinstance(dimensions, Mapping):
            for dimension in dimensions.values():
                if not isinstance(dimension, Mapping):
                    continue
                for key in ("precision_micro", "recall_micro", "f1_micro"):
                    value = dimension.get(key)
                    if not isinstance(value, int) or not 0 <= value <= 1_000_000:
                        blockers.append("grounded answer dimension score must be micro-scaled")
                        break
    if evaluation.get("arm_aggregates") != expected_aggregates:
        blockers.append("grounded answer aggregates mismatch")
    if public_summary != _public_grounded_answer_summary(evaluation):
        blockers.append("public grounded answer summary binding mismatch")


def _validate_private_source_binding(
    safe: Mapping[str, Any],
    blockers: list[str],
    *,
    private_manifest_payload: Mapping[str, Any] | None,
    private_rows_payload: Mapping[str, Any] | None,
    sources: SourceBundle | None,
    private_dir: Path | None,
) -> list[Mapping[str, Any]]:
    if private_manifest_payload is None or private_rows_payload is None or sources is None:
        blockers.append("private artifacts and source reports are required for full validation")
        return []
    if private_dir is None:
        blockers.append("private artifact directory is required for security validation")
    else:
        try:
            _assert_symlink_safe(private_dir)
            if (private_dir.stat().st_mode & 0o777) != 0o700:
                blockers.append("private artifact directory mode must be 0700")
            for filename in (PRIVATE_MANIFEST_FILENAME, PRIVATE_ROWS_FILENAME):
                path = private_dir / filename
                _assert_symlink_safe(path)
                if not path.is_file() or (path.stat().st_mode & 0o777) != 0o600:
                    blockers.append(f"private artifact mode must be 0600: {filename}")
        except (OSError, RuntimeError):
            blockers.append("private artifact path security validation failed")
    source_binding = _source_binding(sources)
    source_binding_hash = sha256_json(source_binding)
    if safe.get("source_binding_hash") != source_binding_hash:
        blockers.append("public source binding hash mismatch")
    if safe.get("source_hashes") != source_binding["source_hashes"]:
        blockers.append("public source hashes mismatch")
    for name, payload, expected_type_key, expected_type in (
        ("private manifest", private_manifest_payload, "manifest_type", PRIVATE_MANIFEST_TYPE),
        ("private rows", private_rows_payload, "rows_type", PRIVATE_ROWS_TYPE),
    ):
        if payload.get(expected_type_key) != expected_type:
            blockers.append(f"{name} type mismatch")
        if payload.get("source_binding_hash") != source_binding_hash:
            blockers.append(f"{name} source binding hash mismatch")
    manifest_rows = private_manifest_payload.get("cases")
    result_rows = private_rows_payload.get("rows")
    if not isinstance(manifest_rows, list) or any(
        not isinstance(row, Mapping) for row in manifest_rows
    ):
        blockers.append("private manifest rows must be objects")
        return []
    if not isinstance(result_rows, list) or any(
        not isinstance(row, Mapping) for row in result_rows
    ):
        blockers.append("private result rows must be objects")
        return []
    if len(manifest_rows) != len(result_rows):
        blockers.append("private artifact row counts mismatch")
        return []
    manifest_rows_hash = sha256_json(manifest_rows)
    result_rows_hash = sha256_json(result_rows)
    for name, payload in (
        ("private manifest", private_manifest_payload),
        ("private rows", private_rows_payload),
    ):
        if payload.get("private_manifest_rows_hash") != manifest_rows_hash:
            blockers.append(f"{name} manifest row hash mismatch")
        if payload.get("private_result_rows_hash") != result_rows_hash:
            blockers.append(f"{name} result row hash mismatch")
    if safe.get("private_artifact_manifest_hash") != sha256_json(private_manifest_payload):
        blockers.append("public private-manifest artifact hash mismatch")
    if safe.get("private_artifact_rows_hash") != sha256_json(private_rows_payload):
        blockers.append("public private-rows artifact hash mismatch")
    sizes = safe.get("serialized_sizes_bytes")
    if isinstance(sizes, Mapping):
        if sizes.get("private_manifest") != _serialized_json_size(
            private_manifest_payload, compact=True
        ):
            blockers.append("private manifest serialized size mismatch")
        if sizes.get("private_rows") != _serialized_json_size(private_rows_payload, compact=True):
            blockers.append("private rows serialized size mismatch")

    try:
        source_cases = _validate_private_manifest(
            sources.manifest,
            _integer(safe.get("unique_evidence_case_count")),
        )
    except FileNotFoundError:
        blockers.append("source private manifest validation failed")
        return []
    source_case_by_fingerprint = {str(case["private_fingerprint"]): case for case in source_cases}
    source_fingerprints = set(source_case_by_fingerprint)
    baseline_rows = _rows_by_fingerprint(sources.baseline, "case_rows")
    kg_rows = _rows_by_fingerprint(sources.kg_fusion, "case_rows")
    ontology_rows = _rows_by_fingerprint(sources.ontology_ablation, "ablation_rows")
    try:
        grounded_scores = _grounded_arm_scores_by_fingerprint(
            private_rows_payload.get("grounded_answer_evaluation")
            if isinstance(private_rows_payload.get("grounded_answer_evaluation"), Mapping)
            else None
        )
    except ValueError:
        blockers.append("grounded answer score binding is invalid")
        grounded_scores = {}
    rows: list[Mapping[str, Any]] = []
    private_replay = private_rows_payload.get("mcp_replay")
    tools_list_response = (
        private_replay.get("tools_list_response")
        if isinstance(private_replay, Mapping)
        else _simulation_tools_list_response()
    )
    for index, (manifest_row, result_row) in enumerate(
        zip(manifest_rows, result_rows, strict=True)
    ):
        shared_keys = (
            "expanded_case_hash",
            "base_case_private_fingerprint",
            "base_case_hash",
            "scenario_hash",
            "base_case_ordinal",
            "scenario_ordinal",
            "result_kind",
            "actual_mail_result_kind",
        )
        if any(manifest_row.get(key) != result_row.get(key) for key in shared_keys):
            blockers.append(f"private row {index} cross-artifact binding mismatch")
            continue
        fingerprint = str(manifest_row.get("base_case_private_fingerprint"))
        if fingerprint not in source_fingerprints:
            blockers.append(f"private row {index} source fingerprint mismatch")
            continue
        scenario = manifest_row.get("scenario")
        if not isinstance(scenario, Mapping):
            blockers.append(f"private row {index} scenario must be an object")
            continue
        expected_scenario_hash = sha256_json({"policy": POLICY_VERSION, **scenario})
        expected_expanded_hash = sha256_json(
            {
                "base_case_fingerprint": fingerprint,
                "scenario_hash": expected_scenario_hash,
            }
        )
        if manifest_row.get("scenario_hash") != expected_scenario_hash:
            blockers.append(f"private row {index} scenario hash mismatch")
        if manifest_row.get("expanded_case_hash") != expected_expanded_hash:
            blockers.append(f"private row {index} expanded case hash mismatch")
        if manifest_row.get("base_case_hash") != sha256_json(fingerprint):
            blockers.append(f"private row {index} base case hash mismatch")
        result_kind = str(manifest_row.get("result_kind"))
        actual_mail_result_kind = str(manifest_row.get("actual_mail_result_kind"))
        trajectory = manifest_row.get("trajectory")
        if not isinstance(trajectory, list):
            blockers.append(f"private row {index} trajectory must be a list")
            continue
        source_case = source_case_by_fingerprint[fingerprint]
        expected_private_query = _private_user_query(str(source_case["query_text"]), scenario)
        expected_trajectory = _private_trajectory(
            str(source_case["query_text"]),
            expected_private_query,
            scenario,
            actual_result_kind=actual_mail_result_kind,
        )
        if manifest_row.get("user_query") != expected_private_query:
            blockers.append(f"private row {index} rendered user query mismatch")
        if trajectory != expected_trajectory:
            blockers.append(f"private row {index} trajectory state machine mismatch")
        tool_selection_status, argument_contract_status = _trajectory_contract_statuses(
            trajectory,
            tools_list_response,
        )
        if manifest_row.get("tool_selection_status") != tool_selection_status:
            blockers.append(f"private row {index} tool selection status mismatch")
        if manifest_row.get("argument_contract_status") != argument_contract_status:
            blockers.append(f"private row {index} argument contract status mismatch")
        scenario_ordinal = _integer(manifest_row.get("scenario_ordinal"))
        expected_arm_results = [
            _simulate_arm(
                arm=arm,
                result_kind=result_kind,
                scenario=scenario,
                scenario_index=scenario_ordinal,
                source_row={
                    CHATGPT_WITH_MAIL_EVIDENCE: baseline_rows[fingerprint],
                    CHATGPT_WITH_CANDIDATE_KG: kg_rows[fingerprint],
                    CHATGPT_WITH_ONTOLOGY_GUIDED_KG: ontology_rows[fingerprint],
                }.get(arm),
                structured_score=grounded_scores.get(fingerprint, {}).get(arm),
                tool_selection_status=tool_selection_status,
                argument_contract_status=argument_contract_status,
                trajectory=trajectory,
            )
            for arm in MAJOR_ARMS
        ]
        if result_row.get("arm_results") != expected_arm_results:
            blockers.append(f"private row {index} arm results do not match source reports")
        row_without_hash = {
            "expanded_case_hash": result_row.get("expanded_case_hash"),
            "base_case_hash": result_row.get("base_case_hash"),
            "scenario_hash": result_row.get("scenario_hash"),
            "base_case_ordinal": result_row.get("base_case_ordinal"),
            "scenario_ordinal": result_row.get("scenario_ordinal"),
            "result_kind": result_row.get("result_kind"),
            "arm_results": result_row.get("arm_results"),
        }
        row = {**row_without_hash, "row_hash": sha256_json(row_without_hash)}
        if result_row.get("public_row_hash") != row["row_hash"]:
            blockers.append(f"private row {index} public row hash mismatch")
        rows.append(row)
    _validate_public_rows(rows, blockers)
    if safe.get("private_public_row_hash") != sha256_json(rows):
        blockers.append("private public row hash mismatch")
    if safe.get("private_public_row_hash_sequence_hash") != sha256_json(
        [row["row_hash"] for row in rows]
    ):
        blockers.append("private public row hash sequence mismatch")
    return rows


def _validate_public_rows(
    rows: Sequence[Mapping[str, Any]],
    blockers: list[str],
) -> None:
    for index, row in enumerate(rows):
        for hash_key in (
            "expanded_case_hash",
            "base_case_hash",
            "scenario_hash",
            "row_hash",
        ):
            if not _is_sha256(row.get(hash_key)):
                blockers.append(f"public row {index} has invalid {hash_key}")
        row_without_hash = dict(row)
        row_hash = row_without_hash.pop("row_hash", None)
        if row_hash != sha256_json(row_without_hash):
            blockers.append(f"public row {index} row_hash mismatch")
        if row.get("result_kind") not in RESULT_KINDS:
            blockers.append(f"public row {index} has invalid result_kind")
        arm_results = row.get("arm_results")
        if not isinstance(arm_results, list) or len(arm_results) != len(MAJOR_ARMS):
            blockers.append(f"public row {index} must have four arm results")
            continue
        if [result.get("arm") for result in arm_results] != list(MAJOR_ARMS):
            blockers.append(f"public row {index} arm order mismatch")
        for result in arm_results:
            _validate_arm_result(index, result, blockers)
        if len(blockers) > 100:
            return


def _validate_arm_result(
    row_index: int,
    result: Mapping[str, Any],
    blockers: list[str],
) -> None:
    for key in (
        "overall_status",
        "tool_selection_status",
        "argument_contract_status",
        "retrieval_status",
        "final_answer_status",
        "citation_status",
        "actionability_status",
        "no_match_permission_safety_status",
    ):
        if result.get(key) not in VALID_STATUSES:
            blockers.append(f"public row {row_index} has invalid {key}")
    for key in ("tool_call_count", "trajectory_turn_count", "simulated_cost_ms"):
        if _integer(result.get(key)) < 0:
            blockers.append(f"public row {row_index} has invalid {key}")
    for key in ("argument_contract_hash", "source_status_hash", "result_hash"):
        if not _is_sha256(result.get(key)):
            blockers.append(f"public row {row_index} has invalid {key}")
    score_hash = result.get("structured_answer_score_hash")
    if score_hash is not None and not _is_sha256(score_hash):
        blockers.append(f"public row {row_index} has invalid structured answer score hash")
    score_micro = result.get("structured_answer_overall_score_micro")
    if score_micro is not None and not (
        isinstance(score_micro, int)
        and not isinstance(score_micro, bool)
        and 0 <= score_micro <= 1_000_000
    ):
        blockers.append(f"public row {row_index} has invalid structured answer score")
    result_without_hash = dict(result)
    result_hash = result_without_hash.pop("result_hash", None)
    if result_hash != sha256_json(result_without_hash):
        blockers.append(f"public row {row_index} arm result hash mismatch")


def _validate_blocked(
    metrics: Mapping[str, Any],
    safe: Mapping[str, Any],
    claim_boundary: Mapping[str, Any],
    blockers: list[str],
) -> None:
    reason = metrics.get("blocked_reason")
    if reason not in _BLOCKED_REASONS:
        blockers.append("blocked reason is not allowlisted")
    if metrics.get("offline_eval_completed") is not False:
        blockers.append("blocked report must not be completed")
    if safe.get("expanded_case_count") != 0:
        blockers.append("blocked report expanded_case_count must be 0")
    if not _is_sha256(safe.get("blocker_hash")):
        blockers.append("blocked report blocker_hash must be sha256")
    _validate_claim_boundary(claim_boundary, supported=False, blockers=blockers)


def _validate_claim_boundary(
    claim_boundary: Mapping[str, Any],
    *,
    supported: bool,
    supports_grounded_replay: bool = False,
    blockers: list[str],
) -> None:
    expected = _claim_boundary(
        supported,
        supports_grounded_replay=supports_grounded_replay,
    )
    if dict(claim_boundary) != expected:
        blockers.append("claim boundary mismatch")


def _claim_boundary(
    supports_eval: bool,
    *,
    supports_grounded_replay: bool = False,
) -> dict[str, bool]:
    return {
        "supports_deterministic_model_free_chatgpt_mcp_simulation_claim": supports_eval,
        "supports_real_in_process_mcp_jsonrpc_replay_claim": (
            supports_eval and supports_grounded_replay
        ),
        "supports_evidence_derived_structured_answer_support_claim": (
            supports_eval and supports_grounded_replay
        ),
        "supports_human_authored_gold_answer_claim": False,
        "supports_live_chatgpt_quality_claim": False,
        "supports_live_chatgpt_execution_claim": False,
        "supports_business_answer_generation_quality_claim": False,
        "supports_factorial_per_case_result_claim": False,
        "supports_general_full_pst_parser_readiness_claim": False,
        "supports_raw_mail_access_claim": False,
        "supports_canonical_kg_write_claim": False,
        "supports_canonical_type_write_claim": False,
        "supports_user_graph_write_claim": False,
        "supports_wiki_projection_claim": False,
        "supports_production_ready_claim": False,
        "container_verification_required": True,
    }


def _blocked_report(reason: str) -> dict[str, Any]:
    safe_reason = reason if reason in _BLOCKED_REASONS else "offline_eval_failed"
    report = {
        "report_type": REPORT_TYPE,
        "generated_at": GENERATED_AT,
        "metrics": {
            "blocked_reason": safe_reason,
            "raw_leak_guard_passed": True,
            "offline_eval_completed": False,
        },
        "safe_outputs": {
            "blocker_hash": sha256_json(safe_reason),
            "expanded_case_count": 0,
        },
        "claim_boundary": _claim_boundary(False),
    }
    report["validation"] = validate_report(report)
    return report


def _validate_private_manifest(
    manifest: Mapping[str, Any],
    expected_count: int,
) -> list[dict[str, Any]]:
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != expected_count:
        raise FileNotFoundError("private_manifest_invalid")
    validated: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    for case in cases:
        if not isinstance(case, dict):
            raise FileNotFoundError("private_manifest_invalid")
        if case.get("result_kind") not in RESULT_KINDS:
            raise FileNotFoundError("private_manifest_invalid")
        if not isinstance(case.get("query_text"), str) or not case["query_text"]:
            raise FileNotFoundError("private_manifest_invalid")
        fingerprint = case.get("private_fingerprint")
        if not _is_sha256(fingerprint) or fingerprint in fingerprints:
            raise FileNotFoundError("private_manifest_invalid")
        fingerprints.add(fingerprint)
        for key in (
            "required_source_observation_ids",
            "forbidden_source_observation_ids",
        ):
            values = case.get(key, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise FileNotFoundError("private_manifest_invalid")
        validated.append(case)
    return validated


def _validated_rows(
    report: Mapping[str, Any],
    *,
    rows_key: str,
    status_key: str,
    expected_count: int,
    invalid_reason: str,
) -> list[dict[str, Any]]:
    rows = _safe_outputs(report).get(rows_key)
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise FileNotFoundError(invalid_reason)
    validated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise FileNotFoundError(invalid_reason)
        if not _is_sha256(row.get("case_manifest_entry_hash")):
            raise FileNotFoundError(invalid_reason)
        if row.get(status_key) not in {STATUS_PASSED, STATUS_FAILED, "unknown"}:
            raise FileNotFoundError(invalid_reason)
        validated.append(row)
    return validated


def _factorial_summaries(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries = _safe_outputs(report).get("arm_summaries")
    if not isinstance(summaries, list):
        raise FileNotFoundError("ontology_factorial_report_invalid")
    validated: list[dict[str, Any]] = []
    for summary in summaries:
        if not isinstance(summary, dict):
            raise FileNotFoundError("ontology_factorial_report_invalid")
        if not _is_sha256(summary.get("arm_id_hash")):
            raise FileNotFoundError("ontology_factorial_report_invalid")
        if not _is_sha256(summary.get("arm_summary_hash")):
            raise FileNotFoundError("ontology_factorial_report_invalid")
        if not isinstance(summary.get("operator_order"), list):
            raise FileNotFoundError("ontology_factorial_report_invalid")
        for key in (
            "operator_count",
            "passed_case_count",
            "pass_rate_basis_points",
            "elapsed_ms",
        ):
            if _integer(summary.get(key)) < 0:
                raise FileNotFoundError("ontology_factorial_report_invalid")
        validated.append(summary)
    return validated


def _rows_by_fingerprint(
    report: Mapping[str, Any],
    rows_key: str,
) -> dict[str, dict[str, Any]]:
    rows = _safe_outputs(report)[rows_key]
    return {str(row["case_manifest_entry_hash"]): row for row in rows}


def _safe_outputs(report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = report.get("safe_outputs")
    if not isinstance(value, Mapping):
        raise FileNotFoundError("offline_eval_failed")
    return value


def _assert_no_source_secrets(report: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    public_strings = _string_values(report)
    for case in manifest.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        private_values = [case.get("query_text"), case.get("case_id")]
        private_values.extend(case.get("required_source_observation_ids", []))
        private_values.extend(case.get("forbidden_source_observation_ids", []))
        for value in private_values:
            if isinstance(value, str) and value and value in public_strings:
                raise RuntimeError("public report contains private source value")
    assert_no_public_raw_references(report, "chatgpt_mcp_eval_report")


def _string_values(value: Any) -> set[str]:
    values: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if isinstance(key, str):
                    values.add(key)
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, str):
            values.add(item)

    walk(value)
    return values


def _reject_forbidden_public_fields(value: Any, blockers: list[str]) -> None:
    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized in _FORBIDDEN_PUBLIC_EXACT_KEYS or any(
                    part in normalized for part in _FORBIDDEN_PUBLIC_KEY_PARTS
                ):
                    blockers.append("public report contains forbidden private field")
                    return
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(_without_validation(value))


def _without_validation(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "validation"}


def _mapping(value: Any, name: str, blockers: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"{name} must be an object")
        return {}
    return value


def _validation(passed: bool, blockers: Sequence[str]) -> dict[str, Any]:
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "validator": REPORT_TYPE + "_validator_v1",
        "passed": passed,
        "blockers": unique_blockers,
        "blocker_count": len(unique_blockers),
        "claim_boundary": {
            "supports_saved_public_report_validation_claim": passed,
            "supports_live_chatgpt_quality_claim": False,
        },
    }


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else -1


def _basis_points(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int((numerator / denominator) * 10_000)


def _milli_average(total: int, count: int) -> int:
    if count <= 0:
        return 0
    return int((total / count) * 1000)


def _micro_average(total_micro: int, count: int) -> int:
    if count <= 0:
        return 0
    return int(round(total_micro / count))


def _source_binding(sources: SourceBundle) -> dict[str, Any]:
    cases = _validate_private_manifest(
        sources.manifest,
        len(sources.manifest.get("cases", [])),
    )
    return {
        "source_hashes": {
            "private_manifest_hash": sha256_json(sources.manifest),
            "baseline_report_hash": sha256_json(_without_validation(sources.baseline)),
            "kg_fusion_report_hash": sha256_json(_without_validation(sources.kg_fusion)),
            "ontology_ablation_report_hash": sha256_json(
                _without_validation(sources.ontology_ablation)
            ),
            "ontology_factorial_report_hash": sha256_json(
                _without_validation(sources.ontology_factorial)
            ),
        },
        "source_report_types": {
            "baseline": sources.baseline.get("report_type"),
            "kg_fusion": sources.kg_fusion.get("report_type"),
            "ontology_ablation": sources.ontology_ablation.get("report_type"),
            "ontology_factorial": sources.ontology_factorial.get("report_type"),
        },
        "private_fingerprint_sequence_hash": sha256_json(
            [case["private_fingerprint"] for case in cases]
        ),
        "baseline_case_rows_hash": sha256_json(_safe_outputs(sources.baseline)["case_rows"]),
        "kg_case_rows_hash": sha256_json(_safe_outputs(sources.kg_fusion)["case_rows"]),
        "ontology_case_rows_hash": sha256_json(
            _safe_outputs(sources.ontology_ablation)["ablation_rows"]
        ),
        "factorial_arm_summaries_hash": sha256_json(
            _safe_outputs(sources.ontology_factorial)["arm_summaries"]
        ),
    }


def _peak_rss_bytes() -> int:
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if sys.platform == "darwin" else peak * 1024


def _render_json(payload: Any, *, compact: bool) -> bytes:
    if compact:
        rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    else:
        rendered = json.dumps(payload, indent=2, sort_keys=True)
    return (rendered + "\n").encode("utf-8")


def _serialized_json_size(payload: Any, *, compact: bool) -> int:
    return len(_render_json(payload, compact=compact))


def _stabilize_public_core_size(report: dict[str, Any]) -> None:
    sizes = report["safe_outputs"]["serialized_sizes_bytes"]
    for _ in range(10):
        measured = _serialized_json_size(_without_validation(report), compact=True)
        if sizes["public_report_without_validation"] == measured:
            return
        sizes["public_report_without_validation"] = measured
    raise RuntimeError("public report serialized size did not stabilize")


def _assert_symlink_safe(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise RuntimeError("private artifact path contains symlink")


def _write_private_artifacts_atomic(
    private_dir: Path,
    payloads: Mapping[str, Any],
) -> dict[str, int]:
    _assert_symlink_safe(private_dir)
    private_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(private_dir, 0o700)
    _assert_symlink_safe(private_dir)
    token = secrets.token_hex(12)
    rendered = {name: _render_json(payload, compact=True) for name, payload in payloads.items()}
    temporary: dict[str, Path] = {}
    backups: dict[str, Path] = {}
    installed: list[Path] = []
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        for name, content in rendered.items():
            target = private_dir / name
            _assert_symlink_safe(target)
            temporary_path = private_dir / f".{name}.{token}.tmp"
            descriptor = os.open(temporary_path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary[name] = temporary_path
        for name in rendered:
            target = private_dir / name
            if target.exists():
                if not target.is_file() or target.is_symlink():
                    raise RuntimeError("private artifact target must be a regular file")
                backup = private_dir / f".{name}.{token}.bak"
                os.replace(target, backup)
                backups[name] = backup
        for name in rendered:
            target = private_dir / name
            os.replace(temporary[name], target)
            os.chmod(target, 0o600)
            installed.append(target)
        directory_descriptor = os.open(private_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        for backup in backups.values():
            backup.unlink()
        return {name: len(content) for name, content in rendered.items()}
    except Exception:
        for target in installed:
            target.unlink(missing_ok=True)
        for name, backup in backups.items():
            if backup.exists():
                os.replace(backup, private_dir / name)
        raise
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        for path in backups.values():
            path.unlink(missing_ok=True)


def _read_json(path: Path, missing_reason: str) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(missing_reason)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileNotFoundError(missing_reason) from exc
    if not isinstance(value, dict):
        raise FileNotFoundError(missing_reason)
    return value


def _write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_render_json(payload, compact=compact))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--private-manifest", type=Path, default=DEFAULT_PRIVATE_MANIFEST)
    parser.add_argument("--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--kg-fusion-report", type=Path, default=DEFAULT_KG_FUSION_REPORT)
    parser.add_argument(
        "--ontology-ablation-report",
        type=Path,
        default=DEFAULT_ONTOLOGY_ABLATION_REPORT,
    )
    parser.add_argument(
        "--ontology-factorial-report",
        type=Path,
        default=DEFAULT_ONTOLOGY_FACTORIAL_REPORT,
    )
    parser.add_argument("--private-dir", type=Path, default=DEFAULT_PRIVATE_DIR)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_CORPUS_ROOT)
    parser.add_argument("--bundle-cache", type=Path, default=None)
    parser.add_argument("--replay-cache", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.validate_report is not None:
        try:
            report = _read_json(args.validate_report, "offline_eval_failed")
        except FileNotFoundError:
            validation = _validation(False, ["validation report missing or invalid"])
        else:
            if "blocked_reason" in report.get("metrics", {}):
                validation = validate_report(report)
            else:
                try:
                    expected_count = _integer(
                        report.get("safe_outputs", {}).get("unique_evidence_case_count")
                    )
                    trusted_replay_attestation_hash = None
                    expected_grounded_answer_evaluation = None
                    if expected_count == PRODUCTION_BASE_CASE_COUNT:
                        if args.replay_cache is None or args.bundle_cache is None:
                            raise FileNotFoundError("offline_eval_failed")
                        replay_artifact = load_replay_artifact(args.replay_cache)
                        trusted_replay_attestation_hash = replay_artifact.attestation_hash
                    sources = _load_and_validate_sources(
                        private_manifest_path=args.private_manifest,
                        baseline_report_path=args.baseline_report,
                        kg_fusion_report_path=args.kg_fusion_report,
                        ontology_ablation_report_path=args.ontology_ablation_report,
                        ontology_factorial_report_path=args.ontology_factorial_report,
                        expected_base_case_count=expected_count,
                    )
                    if expected_count == PRODUCTION_BASE_CASE_COUNT:
                        cases = _validate_private_manifest(sources.manifest, expected_count)
                        expected_fingerprints = {str(case["private_fingerprint"]) for case in cases}
                        replay_fingerprints = {
                            str(row.get("case_fingerprint")) for row in replay_artifact.public_rows
                        }
                        if (
                            replay_artifact.unique_evidence_case_count != len(cases)
                            or replay_fingerprints != expected_fingerprints
                        ):
                            raise FileNotFoundError("offline_eval_failed")
                        bundle = load_or_rebuild_may_mail_evidence_bundle(
                            args.corpus_root,
                            sources.manifest,
                            cache_path=args.bundle_cache,
                        )
                        expected_grounded_answer_evaluation = _build_grounded_answer_evaluation(
                            bundle=bundle,
                            cases=cases,
                            replay_artifact=replay_artifact,
                            corpus_root=args.corpus_root,
                        )
                    private_manifest_payload = _read_json(
                        args.private_dir / PRIVATE_MANIFEST_FILENAME,
                        "offline_eval_failed",
                    )
                    private_rows_payload = _read_json(
                        args.private_dir / PRIVATE_ROWS_FILENAME,
                        "offline_eval_failed",
                    )
                except FileNotFoundError:
                    validation = _validation(
                        False,
                        ["private artifacts or source reports missing or invalid"],
                    )
                else:
                    validation = validate_report(
                        report,
                        private_manifest_payload=private_manifest_payload,
                        private_rows_payload=private_rows_payload,
                        sources=sources,
                        private_dir=args.private_dir,
                        expected_replay_attestation_hash=trusted_replay_attestation_hash,
                        expected_grounded_answer_evaluation=(expected_grounded_answer_evaluation),
                    )
        _write_json(args.output, validation)
        return 0 if validation["passed"] else 1

    if not args.run:
        report = _blocked_report("explicit_run_flag_required")
    else:
        report = run_chatgpt_mcp_50000_eval(
            private_manifest_path=args.private_manifest,
            baseline_report_path=args.baseline_report,
            kg_fusion_report_path=args.kg_fusion_report,
            ontology_ablation_report_path=args.ontology_ablation_report,
            ontology_factorial_report_path=args.ontology_factorial_report,
            private_dir=args.private_dir,
            corpus_root=args.corpus_root,
            bundle_cache_path=args.bundle_cache,
            replay_cache_path=args.replay_cache,
        )
    _write_json(args.output, report, compact=True)
    return 0 if report.get("metrics", {}).get("offline_eval_completed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
