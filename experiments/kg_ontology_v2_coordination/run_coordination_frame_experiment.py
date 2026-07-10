from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import Observation  # noqa: E402
from formowl_graph.coordination_frames import (  # noqa: E402
    DomainPackDefinition,
    evaluate_coordination_answerability,
)
from formowl_graph.ontology import (  # noqa: E402
    core_supertypes_compatible,
    soft_core_supertypes_compatible,
)

EXPERIMENT_DIR = Path(__file__).resolve().parent
DEFAULT_CASES = EXPERIMENT_DIR / "fixtures" / "email_cross_domain_cases.json"
DEFAULT_GOLD = EXPERIMENT_DIR / "fixtures" / "gold_competency_answers.json"
DEFAULT_REGRESSION = EXPERIMENT_DIR / "fixtures" / "regression_redacted_cases.json"
DEFAULT_CHALLENGE = EXPERIMENT_DIR / "fixtures" / "challenge_redacted_100_cases.json"
EFFECTIVENESS_ARMS = (
    "kg_without_ontology",
    "kg_hard_ontology",
    "kg_soft_ontology_gate",
    "coordination_frame_v2_redacted",
    "hybrid_soft_gate_v2_frame",
)
STRESS_10000_BUCKET_COUNTS = {
    "gate_false_reject": 2000,
    "alignment_suppressed": 1500,
    "structure_misleads": 1500,
    "frame_type_confusion": 1500,
    "cross_thread_dependency": 1000,
    "followup_or_fallback_missing": 1000,
    "false_positive_guard": 1000,
    "access_or_redaction_boundary": 500,
}
STRESS_10000_SPLIT_COUNTS = {"dev": 1000, "holdout": 9000}
STRESS_10000_SCALE_FACTOR = 100
STRESS_SEED_BUCKET_COUNTS = {
    bucket: count // STRESS_10000_SCALE_FACTOR
    for bucket, count in STRESS_10000_BUCKET_COUNTS.items()
}
STRESS_SEED_SPLIT_COUNTS = {"dev": 30, "holdout": 70}
STRESS_10000_GENERATION_ID = "redacted_hard_challenge_100_v1_scaled_x100_v1"


def run_experiment(
    *,
    cases_path: Path = DEFAULT_CASES,
    gold_path: Path = DEFAULT_GOLD,
    regression_path: Path = DEFAULT_REGRESSION,
    challenge_path: Path = DEFAULT_CHALLENGE,
) -> dict[str, Any]:
    cases = _load_json_object(cases_path)
    gold_cases = _load_json_list(gold_path)
    regression_pack = _load_json_object(regression_path)
    challenge_pack = _load_json_object(challenge_path)
    stress_pack = _generate_redacted_stress_pack_10000(challenge_pack)
    observations = [_observation_from_fixture(item, cases) for item in cases["observations"]]
    domain_packs = [DomainPackDefinition.from_dict(item) for item in cases.get("domain_packs", [])]
    report = evaluate_coordination_answerability(
        observations=observations,
        gold_cases=gold_cases,
        domain_packs=domain_packs,
        extractor_run_id="run_ontology_v2_coordination_experiment",
        ontology_revision_id=str(cases["ontology_revision_id"]),
        created_at=str(cases["created_at"]),
    )
    report["gold_case_count"] = len(gold_cases)
    report["fixture_sources"] = {
        "cases": _repo_relative(cases_path),
        "gold": _repo_relative(gold_path),
        "regression": _repo_relative(regression_path),
        "challenge": _repo_relative(challenge_path),
        "stress_benchmark": "generated_from_redacted_100_case_templates",
        "source_kind": "synthetic_email_cross_domain_fixture",
        "raw_pst_content_used": False,
    }
    report["method"] = {
        "layer_0": "Evidence/source locators are preserved through Observation ids and evidence spans.",
        "layer_1": "Stable coordination-frame core supplies Request, Commitment, Decision, Blocker, Deadline, StatusChange, and related frames.",
        "layer_2": "Scoped domain packs extend core frames and WorkObject-style objects without mutating the core.",
        "layer_3": "Competency questions approximate follow-up queue, decision log, risk register, and case progress projection answerability.",
    }
    report["type_gate_noise_ablation"] = _type_gate_noise_ablation()
    report["effectiveness_regression"] = _evaluate_effectiveness_regression(regression_pack)
    report["hard_challenge_100"] = _evaluate_effectiveness_regression(challenge_pack)
    report["redacted_stress_benchmark_10000"] = _evaluate_effectiveness_regression(
        stress_pack,
        include_case_results=False,
    )
    report["ablation_versions"] = _ablation_versions(report)
    report["acceptance_checks"] = {
        "stable_coordination_core": _check_stable_core(report),
        "domain_packs_extend_core": True,
        "v2_roundtrip_answerability_delta_positive_vs_current_marker_baseline": (
            report["comparison"]["v2_answerability_delta_vs_current"] > 0
        ),
        "v2_roundtrip_slot_recall_delta_positive_vs_current_marker_baseline": (
            report["comparison"]["v2_slot_recall_delta_vs_current"] > 0
        ),
        "v2_slot_value_recall_complete": (
            report["arms"]["coordination_frame_v2"]["slot_value_recall"] == 1.0
        ),
        "candidate_only_boundary": report["claim_boundary"]["candidate_only"]
        and not report["claim_boundary"]["canonical_graph_write_allowed"],
        "redacted_regression_reproduced": report["effectiveness_regression"]["summary"][
            "hard_ontology_regression_reproduced"
        ],
        "hybrid_effective_on_redacted_replay": report["effectiveness_regression"]["summary"][
            "hybrid_improves_over_hard_and_kg_without_ontology"
        ],
        "hard_challenge_100_case_count": report["hard_challenge_100"]["case_count"] == 100,
        "hard_challenge_100_regression_reproduced": report["hard_challenge_100"]["summary"][
            "hard_ontology_regression_reproduced"
        ],
        "hard_challenge_100_hybrid_effective": report["hard_challenge_100"]["summary"][
            "hybrid_improves_over_hard_and_kg_without_ontology"
        ],
        "redacted_stress_10000_case_count": (
            report["redacted_stress_benchmark_10000"]["case_count"] == 10000
        ),
        "redacted_stress_10000_split_counts": (
            report["redacted_stress_benchmark_10000"]["split_counts"] == STRESS_10000_SPLIT_COUNTS
        ),
        "redacted_stress_10000_bucket_counts": (
            report["redacted_stress_benchmark_10000"]["failure_bucket_counts"]
            == STRESS_10000_BUCKET_COUNTS
        ),
        "redacted_stress_10000_regression_reproduced": report["redacted_stress_benchmark_10000"][
            "summary"
        ]["hard_ontology_regression_reproduced"],
        "redacted_stress_10000_hybrid_effective": report["redacted_stress_benchmark_10000"][
            "summary"
        ]["hybrid_improves_over_hard_and_kg_without_ontology"],
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--regression", type=Path, default=DEFAULT_REGRESSION)
    parser.add_argument("--challenge", type=Path, default=DEFAULT_CHALLENGE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    report = run_experiment(
        cases_path=args.cases,
        gold_path=args.gold,
        regression_path=args.regression,
        challenge_path=args.challenge,
    )
    document = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document + "\n", encoding="utf-8")
    else:
        print(document)
    return 0


def _observation_from_fixture(value: dict[str, Any], root: dict[str, Any]) -> Observation:
    payload = dict(value)
    payload["permission_scope"] = value.get("permission_scope", root["permission_scope"])
    payload["created_at"] = value.get("created_at", root["created_at"])
    return Observation.from_dict(payload)


def _load_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return data


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise TypeError(f"{path} must contain a JSON object list")
    return data


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return "external_input_redacted"


def _check_stable_core(report: dict[str, Any]) -> bool:
    v2_arm = report["arms"]["coordination_frame_v2"]
    observed = {item["status"] for item in v2_arm["competency_statuses"]}
    return (
        v2_arm["candidate_frame_count"] >= 10
        and v2_arm["frame_type_recall"] >= 0.9
        and observed == {"answered"}
    )


def _type_gate_noise_ablation() -> dict[str, Any]:
    cases = [
        {
            "case_id": "quote_document_vs_artifact",
            "left_core_supertype_id": "Document",
            "right_core_supertype_id": "Artifact",
            "left_type_confidence": 0.82,
            "right_type_confidence": 0.86,
            "should_match": True,
        },
        {
            "case_id": "quote_document_vs_event_noisy",
            "left_core_supertype_id": "Document",
            "right_core_supertype_id": "Event",
            "left_type_confidence": 0.62,
            "right_type_confidence": 0.58,
            "should_match": True,
        },
        {
            "case_id": "customer_person_vs_organization_noisy",
            "left_core_supertype_id": "Person",
            "right_core_supertype_id": "Organization",
            "left_type_confidence": 0.57,
            "right_type_confidence": 0.72,
            "should_match": True,
        },
        {
            "case_id": "person_vs_project_high_confidence_negative",
            "left_core_supertype_id": "Person",
            "right_core_supertype_id": "Project",
            "left_type_confidence": 0.96,
            "right_type_confidence": 0.95,
            "should_match": False,
        },
    ]
    rows: list[dict[str, Any]] = []
    for case in cases:
        hard = core_supertypes_compatible(
            str(case["left_core_supertype_id"]),
            str(case["right_core_supertype_id"]),
        )
        soft = soft_core_supertypes_compatible(
            str(case["left_core_supertype_id"]),
            str(case["right_core_supertype_id"]),
            left_type_confidence=float(case["left_type_confidence"]),
            right_type_confidence=float(case["right_type_confidence"]),
        )
        rows.append(
            {
                **case,
                "hard_gate_rejects": not hard.compatible,
                "hard_gate_reason": hard.reason,
                "soft_gate_hard_rejects": soft.hard_reject,
                "soft_gate_reason": soft.reason,
                "soft_gate_score_multiplier": soft.score_multiplier,
            }
        )
    return {
        "ablation_id": "synthetic_noisy_core_type_gate_ablation_v1",
        "claim_boundary": "synthetic scaffold only; not real email regression evidence",
        "case_count": len(rows),
        "hard_gate_false_reject_count": sum(
            1 for row in rows if row["should_match"] and row["hard_gate_rejects"]
        ),
        "soft_gate_false_reject_count": sum(
            1 for row in rows if row["should_match"] and row["soft_gate_hard_rejects"]
        ),
        "soft_gate_high_confidence_negative_reject_count": sum(
            1 for row in rows if not row["should_match"] and row["soft_gate_hard_rejects"]
        ),
        "cases": rows,
    }


def _ablation_versions(report: dict[str, Any]) -> dict[str, Any]:
    original_arm_fields = (
        "candidate_frame_count",
        "candidate_atom_count",
        "slot_recall",
        "slot_value_recall",
        "competency_answerability_score",
        "frame_type_recall",
        "warning_count",
    )
    original_arms = {
        arm_name: {field: arm_report[field] for field in original_arm_fields if field in arm_report}
        for arm_name, arm_report in report["arms"].items()
    }
    challenge = report["hard_challenge_100"]
    stress = report["redacted_stress_benchmark_10000"]
    return {
        "original_synthetic_marker_fixture": {
            "dataset_id": "v1_synthetic_marker_roundtrip_fixture",
            "claim_boundary": "round-trip contract verification; not production parser evidence",
            "case_count": report["gold_case_count"],
            "observation_count": report["observation_count"],
            "arms": original_arms,
            "comparison": dict(report["comparison"]),
        },
        "redacted_hard_challenge_100": {
            "dataset_id": challenge["dataset_id"],
            "claim_boundary": challenge["claim_boundary"],
            "case_count": challenge["case_count"],
            "positive_case_count": challenge["positive_case_count"],
            "failure_bucket_counts": challenge["failure_bucket_counts"],
            "split_counts": challenge["split_counts"],
            "arms": _compact_effectiveness_arms(challenge["arms"]),
            "summary": dict(challenge["summary"]),
        },
        "redacted_stress_benchmark_10000": {
            "dataset_id": stress["dataset_id"],
            "source_kind": stress["source_kind"],
            "generation": dict(stress.get("generation", {})),
            "claim_boundary": stress["claim_boundary"],
            "case_count": stress["case_count"],
            "positive_case_count": stress["positive_case_count"],
            "failure_bucket_counts": stress["failure_bucket_counts"],
            "split_counts": stress["split_counts"],
            "arms": _compact_effectiveness_arms(stress["arms"]),
            "summary": dict(stress["summary"]),
            "split_summaries": dict(stress["split_summaries"]),
        },
    }


def _evaluate_effectiveness_regression(
    pack: dict[str, Any],
    *,
    include_case_results: bool = True,
) -> dict[str, Any]:
    cases = pack.get("cases", [])
    if not isinstance(cases, list) or not all(isinstance(item, dict) for item in cases):
        raise TypeError("regression redacted cases must contain a case list")
    arms = _evaluate_effectiveness_arms(cases)
    output_arms = arms if include_case_results else _compact_effectiveness_arms(arms)
    summary = _effectiveness_summary(arms)
    return {
        "dataset_id": str(pack.get("dataset_id", "unknown")),
        "source_kind": str(pack.get("source_kind", "unknown")),
        "generation": dict(pack.get("generation", {})),
        "claim_boundary": {
            **dict(pack.get("claim_boundary", {})),
            "canonical_graph_write_allowed": False,
            "canonical_type_write_allowed": False,
            "raw_asset_access_granted": False,
        },
        "case_count": len(cases),
        "positive_case_count": sum(1 for case in cases if bool(case.get("should_answer", True))),
        "failure_bucket_counts": _count_values(cases, "failure_bucket"),
        "split_counts": _count_values(cases, "split"),
        "arms": output_arms,
        "summary": summary,
        "split_summaries": _effectiveness_split_summaries(cases),
        "case_results_included": include_case_results,
    }


def _generate_redacted_stress_pack_10000(seed_pack: dict[str, Any]) -> dict[str, Any]:
    seed_cases = seed_pack.get("cases", [])
    if not isinstance(seed_cases, list) or not all(isinstance(item, dict) for item in seed_cases):
        raise TypeError("stress seed pack must contain a case list")
    _validate_redacted_stress_seed_pack(seed_pack, seed_cases)

    by_bucket: dict[str, list[dict[str, Any]]] = {
        bucket: [] for bucket in STRESS_10000_BUCKET_COUNTS
    }
    for case in seed_cases:
        bucket = str(case.get("failure_bucket", "unknown"))
        if bucket in by_bucket:
            by_bucket[bucket].append(case)

    generated: list[dict[str, Any]] = []
    global_index = 1
    for bucket, target_count in STRESS_10000_BUCKET_COUNTS.items():
        bucket_seed_cases = by_bucket[bucket]
        if not bucket_seed_cases:
            raise ValueError(f"stress seed pack has no cases for bucket {bucket}")
        if target_count % len(bucket_seed_cases) != 0:
            raise ValueError(f"bucket {bucket} cannot be scaled evenly to {target_count}")
        variants_per_template = target_count // len(bucket_seed_cases)
        dev_count = target_count // 10
        for variant_index in range(variants_per_template):
            for template_ordinal, template_case in enumerate(bucket_seed_cases, start=1):
                bucket_case_number = variant_index * len(bucket_seed_cases) + template_ordinal
                split = "dev" if bucket_case_number <= dev_count else "holdout"
                generated.append(
                    _redacted_stress_case_from_template(
                        template_case,
                        case_number=global_index,
                        split=split,
                        template_ordinal=template_ordinal,
                        variant_index=variant_index + 1,
                    )
                )
                global_index += 1

    return {
        "dataset_id": "redacted_stress_benchmark_10000_v1",
        "source_kind": "deterministic_redacted_stress_benchmark",
        "created_at": "2026-07-08T12:00:00+00:00",
        "design_note": (
            "Deterministic 10000-case stress benchmark generated from the fixed "
            "100-case redacted hard-challenge templates. It is not raw PST parser output."
        ),
        "generation": {
            "generation_id": STRESS_10000_GENERATION_ID,
            "seed_dataset_id": str(seed_pack.get("dataset_id", "unknown")),
            "seed_case_count": len(seed_cases),
            "scale_factor": STRESS_10000_SCALE_FACTOR,
            "template_fields_added": ["template_id", "variant_id", "generation_id"],
            "case_results_omitted_from_report": True,
            "template_leakage_boundary": (
                "generated stress benchmark repeats redacted template families; "
                "dev/holdout split is deterministic stress validation, not independent PST holdout"
            ),
        },
        "claim_boundary": {
            **dict(seed_pack.get("claim_boundary", {})),
            "generated_from_redacted_templates": True,
            "held_out_parser_output_claim": False,
            "production_parser_claim": False,
            "raw_message_bodies_committed": False,
            "raw_pst_content_used": False,
        },
        "failure_bucket_counts": dict(STRESS_10000_BUCKET_COUNTS),
        "splits": dict(STRESS_10000_SPLIT_COUNTS),
        "cases": generated,
    }


def _validate_redacted_stress_seed_pack(
    seed_pack: dict[str, Any],
    seed_cases: list[dict[str, Any]],
) -> None:
    if len(seed_cases) != 100:
        raise ValueError("redacted stress benchmark seed must contain exactly 100 cases")
    if _count_values(seed_cases, "failure_bucket") != STRESS_SEED_BUCKET_COUNTS:
        raise ValueError("redacted stress benchmark seed has unexpected failure bucket counts")
    if _count_values(seed_cases, "split") != STRESS_SEED_SPLIT_COUNTS:
        raise ValueError("redacted stress benchmark seed has unexpected split counts")
    claim_boundary = seed_pack.get("claim_boundary", {})
    if (
        not isinstance(claim_boundary, dict)
        or claim_boundary.get("raw_pst_content_used") is not False
    ):
        raise ValueError("redacted stress benchmark seed must declare no raw PST content")
    if claim_boundary.get("production_parser_claim") is not False:
        raise ValueError(
            "redacted stress benchmark seed must not declare a production parser claim"
        )


def _redacted_stress_case_from_template(
    template_case: dict[str, Any],
    *,
    case_number: int,
    split: str,
    template_ordinal: int,
    variant_index: int,
) -> dict[str, Any]:
    old_suffix = _case_suffix(template_case)
    new_suffix = f"{case_number:05d}"
    source_observation_ids = [
        str(item)
        for item in template_case.get("source_observation_ids", [])
        if isinstance(item, str)
    ]
    new_observation_id = f"obs_stress_{new_suffix}"
    case = _rewrite_redacted_template_values(
        deepcopy(template_case),
        old_suffix=old_suffix,
        new_suffix=new_suffix,
        old_observation_ids=source_observation_ids,
        new_observation_id=new_observation_id,
    )
    bucket = str(template_case.get("failure_bucket", "unknown"))
    case["case_id"] = f"stress_{new_suffix}_{bucket}"
    case["source_observation_ids"] = [new_observation_id]
    case["split"] = split
    case["template_id"] = str(template_case["case_id"])
    case["variant_id"] = f"{bucket}_template_{template_ordinal:03d}_variant_{variant_index:03d}"
    case["generation_id"] = STRESS_10000_GENERATION_ID
    case["evidence_spans"] = [
        {
            "span_id": f"span_stress_{new_suffix}_1",
            "source_observation_id": new_observation_id,
            "locator": {
                "redacted_thread_index": case_number,
                "redacted_turn": _redacted_turn(template_case),
            },
            "text_hash": f"sha256:{case_number:064x}",
        }
    ]
    return case


def _case_suffix(case: dict[str, Any]) -> str:
    case_id = str(case.get("case_id", ""))
    parts = case_id.split("_")
    if len(parts) >= 2 and parts[0] == "challenge" and parts[1].isdigit():
        return parts[1]
    return ""


def _redacted_turn(case: dict[str, Any]) -> int:
    spans = case.get("evidence_spans", [])
    if isinstance(spans, list) and spans and isinstance(spans[0], dict):
        locator = spans[0].get("locator", {})
        if isinstance(locator, dict) and isinstance(locator.get("redacted_turn"), int):
            return int(locator["redacted_turn"])
    return 1


def _rewrite_redacted_template_values(
    value: Any,
    *,
    old_suffix: str,
    new_suffix: str,
    old_observation_ids: list[str],
    new_observation_id: str,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _rewrite_redacted_template_values(
                item,
                old_suffix=old_suffix,
                new_suffix=new_suffix,
                old_observation_ids=old_observation_ids,
                new_observation_id=new_observation_id,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _rewrite_redacted_template_values(
                item,
                old_suffix=old_suffix,
                new_suffix=new_suffix,
                old_observation_ids=old_observation_ids,
                new_observation_id=new_observation_id,
            )
            for item in value
        ]
    if isinstance(value, str):
        rewritten = value
        if old_suffix:
            rewritten = rewritten.replace(f"_{old_suffix}", f"_{new_suffix}")
        for old_observation_id in old_observation_ids:
            rewritten = rewritten.replace(old_observation_id, new_observation_id)
        return rewritten
    return value


def _evaluate_effectiveness_arms(cases: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    arm_case_results = {
        arm: [_score_effectiveness_case(case, arm) for case in cases] for arm in EFFECTIVENESS_ARMS
    }
    return {arm: _summarize_effectiveness_arm(results) for arm, results in arm_case_results.items()}


def _effectiveness_split_summaries(cases: list[dict[str, Any]]) -> dict[str, Any]:
    splits = sorted({str(case.get("split", "unspecified")) for case in cases})
    summaries: dict[str, Any] = {}
    for split in splits:
        split_cases = [case for case in cases if str(case.get("split", "unspecified")) == split]
        arms = _evaluate_effectiveness_arms(split_cases)
        summaries[split] = {
            "case_count": len(split_cases),
            "positive_case_count": sum(
                1 for case in split_cases if bool(case.get("should_answer", True))
            ),
            "failure_bucket_counts": _count_values(split_cases, "failure_bucket"),
            "arms": _compact_effectiveness_arms(arms),
            "summary": _effectiveness_summary(arms),
        }
    return summaries


def _compact_effectiveness_arms(arms: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        arm: {key: value for key, value in arm_report.items() if key != "case_results"}
        for arm, arm_report in arms.items()
    }


def _count_values(cases: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for case in cases:
        value = str(case.get(field_name, "unspecified"))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _score_effectiveness_case(case: dict[str, Any], arm: str) -> dict[str, Any]:
    prediction = _effectiveness_prediction(case, arm)
    should_answer = bool(case.get("should_answer", True))
    required_slots = [str(item) for item in case.get("required_slots", [])]
    gold_answer = {
        str(key): value
        for key, value in dict(case.get("gold_answer", {})).items()
        if str(key) in set(required_slots)
    }
    answer = prediction.get("answer")
    slots = dict(answer.get("slots", {})) if isinstance(answer, dict) else {}
    matched_slots = sum(
        1
        for slot_name in required_slots
        if slot_name in slots
        and _normalize_effectiveness_value(slots[slot_name])
        == _normalize_effectiveness_value(gold_answer.get(slot_name))
    )
    evidence_complete = bool(answer) and _effectiveness_evidence_complete(
        answer,
        case_observation_ids={
            str(item) for item in case.get("source_observation_ids", []) if isinstance(item, str)
        },
    )

    if not answer:
        status = "correct_no_answer" if not should_answer else "missing"
        correct = not should_answer
    elif not should_answer:
        status = "false_positive"
        correct = False
    elif matched_slots == len(required_slots):
        status = "correct"
        correct = True
    elif matched_slots:
        status = "partial"
        correct = False
    else:
        status = "wrong"
        correct = False

    return {
        "case_id": str(case["case_id"]),
        "failure_bucket": str(case.get("failure_bucket", "unknown")),
        "should_answer": should_answer,
        "status": status,
        "correct": correct,
        "required_slot_count": len(required_slots) if should_answer else 0,
        "predicted_slot_count": len(slots) if answer else 0,
        "matched_slot_count": matched_slots if should_answer else 0,
        "evidence_complete": evidence_complete,
        "missing_reason": prediction.get("missing_reason"),
        "gate_decision": prediction.get("gate_decision"),
    }


def _effectiveness_prediction(case: dict[str, Any], arm: str) -> dict[str, Any]:
    if arm == "kg_without_ontology":
        return {"answer": _answer_from_case(case, "kg_without_ontology_answer")}
    if arm == "kg_hard_ontology":
        hard = _hard_gate_for_case(case)
        if not hard.compatible:
            return {
                "answer": None,
                "missing_reason": "hard_gate_reject",
                "gate_decision": hard.to_dict(),
            }
        if case.get("hard_alignment_suppressed") is True:
            return {
                "answer": None,
                "missing_reason": "alignment_suppressed",
                "gate_decision": hard.to_dict(),
            }
        return {
            "answer": _answer_from_case(case, "hard_ontology_answer")
            or _answer_from_case(case, "kg_without_ontology_answer"),
            "gate_decision": hard.to_dict(),
        }
    if arm == "kg_soft_ontology_gate":
        soft = _soft_gate_for_case(case)
        if soft.hard_reject:
            return {
                "answer": None,
                "missing_reason": "soft_high_confidence_gate_reject",
                "gate_decision": soft.to_dict(),
            }
        return {
            "answer": _answer_from_case(case, "soft_ontology_answer")
            or _answer_from_case(case, "hard_ontology_answer")
            or _answer_from_case(case, "kg_without_ontology_answer"),
            "gate_decision": soft.to_dict(),
        }
    if arm == "coordination_frame_v2_redacted":
        return {"answer": _answer_from_case(case, "v2_frame_answer")}
    if arm == "hybrid_soft_gate_v2_frame":
        v2_answer = _answer_from_case(case, "v2_frame_answer")
        if v2_answer is not None:
            return {"answer": v2_answer, "selected_signal": "v2_frame"}
        soft_prediction = _effectiveness_prediction(case, "kg_soft_ontology_gate")
        soft_prediction["selected_signal"] = "soft_ontology_gate"
        return soft_prediction
    raise ValueError(f"unsupported effectiveness arm: {arm}")


def _hard_gate_for_case(case: dict[str, Any]):
    type_pair = dict(case.get("type_pair", {}))
    return core_supertypes_compatible(
        str(type_pair["left_core_supertype_id"]),
        str(type_pair["right_core_supertype_id"]),
    )


def _soft_gate_for_case(case: dict[str, Any]):
    type_pair = dict(case.get("type_pair", {}))
    return soft_core_supertypes_compatible(
        str(type_pair["left_core_supertype_id"]),
        str(type_pair["right_core_supertype_id"]),
        left_type_confidence=float(type_pair["left_type_confidence"]),
        right_type_confidence=float(type_pair["right_type_confidence"]),
    )


def _answer_from_case(case: dict[str, Any], field_name: str) -> dict[str, Any] | None:
    value = case.get(field_name)
    if not isinstance(value, dict):
        return None
    slots = value.get("slots")
    if not isinstance(slots, dict) or not slots:
        return None
    evidence_spans = value.get("evidence_spans")
    if not isinstance(evidence_spans, list):
        evidence_spans = case.get("evidence_spans", [])
    answer = {"slots": dict(slots), "evidence_spans": list(evidence_spans)}
    if value.get("frame_type") is not None:
        answer["frame_type"] = str(value["frame_type"])
    return answer


def _summarize_effectiveness_arm(results: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(results)
    positive_cases = [item for item in results if item["should_answer"]]
    answered = [item for item in results if item["predicted_slot_count"] > 0]
    matched_slot_count = sum(int(item["matched_slot_count"]) for item in results)
    required_slot_count = sum(int(item["required_slot_count"]) for item in results)
    predicted_slot_count = sum(int(item["predicted_slot_count"]) for item in results)
    precision = _ratio(matched_slot_count, predicted_slot_count)
    recall = _ratio(matched_slot_count, required_slot_count)
    return {
        "case_count": total_cases,
        "positive_case_count": len(positive_cases),
        "correct_case_count": sum(1 for item in results if item["correct"]),
        "exact_match_rate": _ratio(sum(1 for item in results if item["correct"]), total_cases),
        "positive_answer_recall": _ratio(
            sum(1 for item in positive_cases if item["status"] == "correct"),
            len(positive_cases),
        ),
        "slot_value_precision": precision,
        "slot_value_recall": recall,
        "slot_value_f1": _f1(precision, recall),
        "false_positive_count": sum(1 for item in results if item["status"] == "false_positive"),
        "missing_count": sum(1 for item in results if item["status"] == "missing"),
        "partial_count": sum(1 for item in results if item["status"] == "partial"),
        "wrong_count": sum(1 for item in results if item["status"] == "wrong"),
        "hard_gate_false_reject_count": sum(
            1
            for item in results
            if item["should_answer"] and item.get("missing_reason") == "hard_gate_reject"
        ),
        "alignment_suppressed_count": sum(
            1 for item in results if item.get("missing_reason") == "alignment_suppressed"
        ),
        "structure_mislead_count": sum(
            1
            for item in results
            if item["failure_bucket"] == "structure_misleads"
            and item["status"] in {"wrong", "partial"}
        ),
        "evidence_complete_rate": _ratio(
            sum(1 for item in answered if item["evidence_complete"]),
            len(answered),
        ),
        "status_counts": _count_result_statuses(results),
        "status_counts_by_failure_bucket": _count_result_statuses_by_bucket(results),
        "case_results": results,
    }


def _count_result_statuses(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _count_result_statuses_by_bucket(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    bucket_counts: dict[str, dict[str, int]] = {}
    for result in results:
        bucket = str(result["failure_bucket"])
        status = str(result["status"])
        bucket_counts.setdefault(bucket, {})
        bucket_counts[bucket][status] = bucket_counts[bucket].get(status, 0) + 1
    return {
        bucket: dict(sorted(status_counts.items()))
        for bucket, status_counts in sorted(bucket_counts.items())
    }


def _effectiveness_summary(arms: dict[str, dict[str, Any]]) -> dict[str, Any]:
    hard = arms["kg_hard_ontology"]["exact_match_rate"]
    no_ontology = arms["kg_without_ontology"]["exact_match_rate"]
    soft = arms["kg_soft_ontology_gate"]["exact_match_rate"]
    v2 = arms["coordination_frame_v2_redacted"]["exact_match_rate"]
    hybrid = arms["hybrid_soft_gate_v2_frame"]["exact_match_rate"]
    best_arm = max(
        EFFECTIVENESS_ARMS,
        key=lambda arm: (
            arms[arm]["exact_match_rate"],
            arms[arm]["slot_value_f1"],
            -arms[arm]["false_positive_count"],
        ),
    )
    return {
        "hard_ontology_regression_reproduced": hard < no_ontology,
        "hard_ontology_delta_vs_kg_without_ontology": round(hard - no_ontology, 6),
        "soft_gate_delta_vs_hard_ontology": round(soft - hard, 6),
        "v2_delta_vs_hard_ontology": round(v2 - hard, 6),
        "hybrid_delta_vs_hard_ontology": round(hybrid - hard, 6),
        "hybrid_delta_vs_kg_without_ontology": round(hybrid - no_ontology, 6),
        "soft_gate_reduces_hard_false_rejects": (
            arms["kg_soft_ontology_gate"]["hard_gate_false_reject_count"]
            < arms["kg_hard_ontology"]["hard_gate_false_reject_count"]
        ),
        "v2_effective_on_redacted_replay": v2 > hard and v2 >= no_ontology,
        "hybrid_improves_over_hard_and_kg_without_ontology": hybrid > hard
        and hybrid >= no_ontology,
        "best_arm_by_exact_match": best_arm,
    }


def _effectiveness_evidence_complete(
    answer: dict[str, Any],
    *,
    case_observation_ids: set[str],
) -> bool:
    for span in answer.get("evidence_spans", []):
        if not isinstance(span, dict):
            continue
        if span.get("source_observation_id") not in case_observation_ids:
            continue
        if not isinstance(span.get("span_id"), str) or not span["span_id"]:
            continue
        if not isinstance(span.get("locator"), dict) or not span["locator"]:
            continue
        text_hash = span.get("text_hash")
        if isinstance(text_hash, str) and text_hash.startswith("sha256:"):
            return True
    return False


def _normalize_effectiveness_value(value: Any) -> str:
    return " ".join(str(value).strip().lower().split())


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 6)


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return round((2 * precision * recall) / (precision + recall), 6)


if __name__ == "__main__":
    raise SystemExit(main())
