"""Fail-closed authority checks for FormOwl methodology and runtime alignment."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable

AUTHORITY_RELATIVE_PATH = Path("docs/methodology-authority.json")

_EXPECTED_AUTHORITY_ID = "formowl_methodology_authority_v1"
_FROZEN_TARGET_PIPELINE = {
    "method_id": "evidence_to_knowledge_kg_ontology_v2_hybrid_v1",
    "tokenizer_id": "jieba_sentencepiece_frozen_profile_candidate_admission_v1",
    "ingestion_policy_id": "complete_source_evidence_output_redaction_v1",
    "evaluation_policy_id": "raw_source_oracle_same_pipeline_end_answer_v1",
}
_TOP_LEVEL_KEYS = {
    "schema_version",
    "authority_id",
    "updated_at",
    "status",
    "target_pipeline",
    "current_runtime",
    "required_gates",
    "claim_policy",
}
_PIPELINE_KEYS = {
    "method_id",
    "tokenizer_id",
    "ingestion_policy_id",
    "evaluation_policy_id",
}
_CURRENT_RUNTIME_KEYS = {
    "method_id",
    "mail_query_tokenizer_id",
    "mail_query_cjk_supported",
    "ingestion_policy_id",
    "evaluation_policy_id",
}
_GATE_KEYS = {"gate_id", "status", "reason_code", "evidence"}
_CLAIM_POLICY_KEYS = {"allowed_claim_ids", "blocked_claim_ids"}
_REQUIRED_GATE_IDS = {
    "runtime_pipeline_matches_target_method",
    "source_completeness_compared_with_raw_oracle",
    "evaluation_reports_bind_execution_fingerprint",
    "same_pipeline_real_source_ablation",
    "real_user_end_answer_acceptance",
}
_REQUIRED_BLOCKED_CLAIM_IDS = {
    "current_runtime_implements_target_method",
    "current_runtime_has_production_chinese_tokenization",
    "historical_real_pst_results_compare_the_current_target_method",
    "kg_outperforms_kg_plus_ontology",
    "kg_plus_ontology_outperforms_kg_on_real_sources",
    "methodology_ready_for_quality_uat",
    "methodology_objective_complete",
}
_REQUIRED_ALLOWED_CLAIM_IDS = {
    "methodology_authority_guard_installed",
    "historical_regex_results_are_diagnostic_only",
    "experiment_layer_jieba_sentencepiece_results",
}
_ASCII_PROBE = "PO470002002 03.80503G301 supplier@example.test"
_CJK_PROBE = "查詢交期與產地"
_EXPECTED_ASCII_PROBE_TOKENS = {
    "po470002002",
    "03.80503g301",
    "supplier@example.test",
}
_EXPECTED_TARGET_CJK_PROBE_TOKENS = {"查詢", "交期", "與", "產地"}
_TOKENIZER_RUNTIME_BINDINGS = (
    Path("python/formowl_mail/query.py"),
    Path("python/formowl_mail/evidence.py"),
)
_TOKENIZER_RUNTIME_CALLERS = {
    Path("python/formowl_mail/query.py"): {
        "_search_visible_bundles",
        "_build_snippet_index",
    },
    Path("python/formowl_mail/evidence.py"): {
        "search_mail_evidence",
        "_query_terms",
    },
}
_TOKENIZER_BINDING_HELPERS = {
    "ascii_identifier_regex_v1": (
        "ascii_identifier_regex_tokens",
        "configured_mail_candidate_admission_tokens",
    ),
    _FROZEN_TARGET_PIPELINE[
        "tokenizer_id"
    ]: (
        "jieba_sentencepiece_frozen_profile_candidate_admission_tokens",
        "configured_mail_candidate_admission_tokens",
    ),
}
_PIPELINE_SOURCE_ROOTS = (
    Path("python/formowl_contract"),
    Path("python/formowl_core"),
    Path("python/formowl_graph"),
    Path("python/formowl_mail"),
)
_PIPELINE_SOURCE_BINDINGS = (
    Path("pyproject.toml"),
    Path("containers/dev/Dockerfile"),
    Path("SPEC.md"),
    Path("RESOURCE_EXTRACTION_SPEC.md"),
    Path("scripts/methodology_authority_check.py"),
    Path("scripts/kg_research_acceptance_suite.py"),
    Path("scripts/mail_full_pst_domain_hard_case_eval.py"),
    Path("scripts/mail_full_pst_domain_hard_kg_fusion_eval.py"),
    Path("scripts/mail_full_pst_domain_hard_ontology_ablation_eval.py"),
    Path("scripts/mail_full_pst_domain_hard_ontology_factorial_eval.py"),
    Path("scripts/mail_full_pst_exm_lexical_ontology_eval.py"),
)
_EXECUTABLE_EVIDENCE_GATE_IDS = _REQUIRED_GATE_IDS - {
    "runtime_pipeline_matches_target_method",
}
_GATE_EVIDENCE_KEYS = {
    "artifact_id",
    "authority_id",
    "gate_id",
    "execution_fingerprint",
    "validator_id",
    "source_manifest_path",
    "source_manifest_sha256",
    "result_artifact_path",
    "result_artifact_sha256",
    "status",
}
_GATE_EVIDENCE_ARTIFACT_ID = "formowl_methodology_gate_evidence_v2"
_GATE_VALIDATOR_IDS = {
    "source_completeness_compared_with_raw_oracle": "raw_source_completeness_validator_v1",
    "evaluation_reports_bind_execution_fingerprint": "execution_report_binding_validator_v1",
    "same_pipeline_real_source_ablation": "same_pipeline_real_source_ablation_validator_v1",
    "real_user_end_answer_acceptance": "real_user_end_answer_acceptance_validator_v1",
}
_GATE_RESULT_ARTIFACT_IDS = {
    "source_completeness_compared_with_raw_oracle": ("formowl_raw_source_completeness_result_v1"),
    "evaluation_reports_bind_execution_fingerprint": ("formowl_execution_report_binding_result_v1"),
    "same_pipeline_real_source_ablation": ("formowl_same_pipeline_real_source_ablation_result_v1"),
    "real_user_end_answer_acceptance": "formowl_real_user_end_answer_result_v1",
}
_SOURCE_MANIFEST_KEYS = {
    "artifact_id",
    "execution_fingerprint",
    "source_kind",
    "source_count",
    "source_item_count",
    "source_hashes",
    "case_manifest_sha256",
    "configuration_manifest_sha256",
    "model_artifact_hashes",
    "package_lock_sha256",
}
_SOURCE_MANIFEST_ARTIFACT_ID = "formowl_methodology_source_manifest_v1"
_RESULT_COMMON_KEYS = {
    "artifact_id",
    "execution_fingerprint",
    "source_manifest_sha256",
    "status",
}
_GATE_RESULT_KEYS = {
    "source_completeness_compared_with_raw_oracle": _RESULT_COMMON_KEYS
    | {
        "raw_source_unit_count",
        "emitted_observation_unit_count",
        "policy_redacted_unit_count",
        "unexplained_loss_unit_count",
        "loss_taxonomy_counts",
    },
    "evaluation_reports_bind_execution_fingerprint": _RESULT_COMMON_KEYS
    | {
        "report_count",
        "bound_report_count",
        "unbound_report_count",
        "report_hashes",
    },
    "same_pipeline_real_source_ablation": _RESULT_COMMON_KEYS
    | {
        "arm_ids",
        "case_count",
        "completed_case_count",
        "adjudicated_case_count",
        "same_source_manifest",
        "same_case_manifest",
        "same_evaluation_policy",
        "result_hashes_by_arm",
    },
    "real_user_end_answer_acceptance": _RESULT_COMMON_KEYS
    | {
        "acceptance_profile_id",
        "case_count",
        "adjudicated_case_count",
        "answerable_case_count",
        "correct_answer_count",
        "citation_supported_correct_count",
        "permission_denial_case_count",
        "permission_denial_pass_count",
        "observed_accuracy_ppm",
        "observed_citation_support_ppm",
    },
}
_ABLATION_ARM_IDS = {"kg_only", "kg_plus_ontology_hybrid_v2"}
_END_ANSWER_ACCEPTANCE_PROFILE_ID = "real_user_end_answer_strict_v1"
_MINIMUM_REAL_USER_CASE_COUNT = 100
_MINIMUM_END_ANSWER_ACCURACY_PPM = 900_000
_REQUIRED_CITATION_SUPPORT_PPM = 1_000_000
_GATE_EXECUTABLE_VALIDATORS: dict[str, Callable[..., bool]] = {}


@dataclass(frozen=True)
class TokenizerProbe:
    tokenizer_id: str
    query_tokenizer_id: str | None
    evidence_tokenizer_id: str | None
    runtime_probe_valid: bool
    ascii_identifier_support: bool
    cjk_support: bool
    query_token_count: int
    evidence_token_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokenizer_id": self.tokenizer_id,
            "query_tokenizer_id": self.query_tokenizer_id,
            "evidence_tokenizer_id": self.evidence_tokenizer_id,
            "runtime_probe_valid": self.runtime_probe_valid,
            "ascii_identifier_support": self.ascii_identifier_support,
            "cjk_support": self.cjk_support,
            "query_token_count": self.query_token_count,
            "evidence_token_count": self.evidence_token_count,
        }


@dataclass(frozen=True)
class MethodologyAuthorityResult:
    authority_valid: bool
    methodology_ready: bool
    authority_id: str | None
    status: str | None
    target_method_id: str | None
    target_tokenizer_id: str | None
    current_method_id: str | None
    current_tokenizer_id: str | None
    blocking_gate_ids: tuple[str, ...]
    blocked_claim_ids: tuple[str, ...]
    execution_fingerprint: str | None
    authority_state_fingerprint: str | None
    pipeline_source_binding_count: int
    tokenizer_probe: TokenizerProbe
    errors: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "formowl_methodology_authority_check_v1",
            "authority_valid": self.authority_valid,
            "methodology_ready": self.methodology_ready,
            "authority_id": self.authority_id,
            "status": self.status,
            "target_method_id": self.target_method_id,
            "target_tokenizer_id": self.target_tokenizer_id,
            "current_method_id": self.current_method_id,
            "current_tokenizer_id": self.current_tokenizer_id,
            "blocking_gate_ids": list(self.blocking_gate_ids),
            "blocked_claim_ids": list(self.blocked_claim_ids),
            "execution_fingerprint": self.execution_fingerprint,
            "authority_state_fingerprint": self.authority_state_fingerprint,
            "pipeline_source_binding_count": self.pipeline_source_binding_count,
            "tokenizer_probe": self.tokenizer_probe.to_dict(),
            "errors": list(self.errors),
        }


def check_methodology_authority(
    *,
    repository_root: Path,
    authority_path: Path | None = None,
) -> MethodologyAuthorityResult:
    """Validate the authority manifest and bind it to observed runtime behavior."""

    path = authority_path or repository_root / AUTHORITY_RELATIVE_PATH
    probe = probe_runtime_tokenizers(repository_root=repository_root)
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _invalid_result(probe, "methodology_authority_manifest_unreadable")

    if not isinstance(payload, dict):
        return _invalid_result(probe, "methodology_authority_manifest_must_be_object")

    _require_exact_keys(payload, _TOP_LEVEL_KEYS, "authority", errors)
    schema_version = payload.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        errors.append("unsupported_methodology_authority_schema")

    authority_id = _string(payload.get("authority_id"), "authority_id", errors)
    if authority_id and authority_id != _EXPECTED_AUTHORITY_ID:
        errors.append("methodology_authority_id_drift")
    updated_at = _string(payload.get("updated_at"), "updated_at", errors)
    if updated_at:
        try:
            date.fromisoformat(updated_at)
        except ValueError:
            errors.append("methodology_authority_updated_at_must_be_iso_date")
    status = payload.get("status")
    if status not in {"blocked", "ready"}:
        errors.append("invalid_methodology_authority_status")
        status = None

    target = _object(payload.get("target_pipeline"), "target_pipeline", errors)
    current = _object(payload.get("current_runtime"), "current_runtime", errors)
    _require_exact_keys(target, _PIPELINE_KEYS, "target_pipeline", errors)
    _require_exact_keys(current, _CURRENT_RUNTIME_KEYS, "current_runtime", errors)

    target_values = {
        key: _string(target.get(key), f"target_pipeline.{key}", errors) for key in _PIPELINE_KEYS
    }
    if target_values != _FROZEN_TARGET_PIPELINE:
        errors.append("frozen_target_pipeline_drift")
    current_method_id = _string(
        current.get("method_id"),
        "current_runtime.method_id",
        errors,
    )
    current_tokenizer_id = _string(
        current.get("mail_query_tokenizer_id"),
        "current_runtime.mail_query_tokenizer_id",
        errors,
    )
    current_ingestion_policy_id = _string(
        current.get("ingestion_policy_id"),
        "current_runtime.ingestion_policy_id",
        errors,
    )
    current_evaluation_policy_id = _string(
        current.get("evaluation_policy_id"),
        "current_runtime.evaluation_policy_id",
        errors,
    )
    declared_cjk_support = current.get("mail_query_cjk_supported")
    if type(declared_cjk_support) is not bool:
        errors.append("current_runtime.mail_query_cjk_supported_must_be_bool")

    if not probe.runtime_probe_valid:
        errors.append("runtime_tokenizer_probe_failed")
    if current_tokenizer_id and current_tokenizer_id != probe.tokenizer_id:
        errors.append("runtime_tokenizer_id_drift")
    if type(declared_cjk_support) is bool and declared_cjk_support != probe.cjk_support:
        errors.append("runtime_cjk_capability_drift")
    runtime_binding_hashes = _validate_pipeline_source_bindings(
        repository_root,
        tokenizer_id=probe.tokenizer_id,
        runtime_probe_valid=probe.runtime_probe_valid,
        errors=errors,
    )

    gates, blocking_gate_ids = _validate_gates(payload.get("required_gates"), errors)
    _validate_gate_evidence_paths(repository_root, gates, errors)
    claim_policy = _object(payload.get("claim_policy"), "claim_policy", errors)
    _require_exact_keys(claim_policy, _CLAIM_POLICY_KEYS, "claim_policy", errors)
    allowed_claim_ids = _string_list(
        claim_policy.get("allowed_claim_ids"),
        "claim_policy.allowed_claim_ids",
        errors,
    )
    blocked_claim_ids = _string_list(
        claim_policy.get("blocked_claim_ids"),
        "claim_policy.blocked_claim_ids",
        errors,
    )
    missing_blocked_claims = _REQUIRED_BLOCKED_CLAIM_IDS.difference(blocked_claim_ids)
    if missing_blocked_claims:
        errors.append("required_methodology_claim_blocks_missing")
    if set(allowed_claim_ids) != _REQUIRED_ALLOWED_CLAIM_IDS:
        errors.append("methodology_allowed_claim_set_mismatch")
    if set(allowed_claim_ids).intersection(blocked_claim_ids):
        errors.append("methodology_claim_policy_overlap")

    expected_status = "ready" if gates and not blocking_gate_ids else "blocked"
    if status and status != expected_status:
        errors.append("methodology_authority_status_inconsistent_with_gates")

    runtime_gate_passed = _gate_status(gates, "runtime_pipeline_matches_target_method") == "passed"
    if runtime_gate_passed or status == "ready":
        if current_method_id != target_values["method_id"]:
            errors.append("passed_runtime_gate_requires_target_runtime_method")
        if current_tokenizer_id != target_values["tokenizer_id"]:
            errors.append("passed_runtime_gate_requires_target_runtime_tokenizer")
        if current_ingestion_policy_id != target_values["ingestion_policy_id"]:
            errors.append("passed_runtime_gate_requires_target_ingestion_policy")
        if current_evaluation_policy_id != target_values["evaluation_policy_id"]:
            errors.append("passed_runtime_gate_requires_target_evaluation_policy")
        if not probe.cjk_support:
            errors.append("passed_runtime_gate_requires_cjk_runtime_support")

    execution_fingerprint, authority_state_fingerprint = _methodology_fingerprints(
        authority_id=authority_id,
        updated_at=updated_at,
        status=status,
        target=target,
        current=current,
        gates=gates,
        claim_policy=claim_policy,
        probe=probe,
        runtime_binding_hashes=runtime_binding_hashes,
    )
    _validate_passed_gate_evidence(
        repository_root=repository_root,
        authority_id=authority_id,
        gates=gates,
        execution_fingerprint=execution_fingerprint,
        errors=errors,
    )
    authority_valid = not errors
    methodology_ready = authority_valid and status == "ready" and not blocking_gate_ids
    return MethodologyAuthorityResult(
        authority_valid=authority_valid,
        methodology_ready=methodology_ready,
        authority_id=authority_id,
        status=status,
        target_method_id=target_values["method_id"],
        target_tokenizer_id=target_values["tokenizer_id"],
        current_method_id=current_method_id,
        current_tokenizer_id=current_tokenizer_id,
        blocking_gate_ids=tuple(sorted(blocking_gate_ids)),
        blocked_claim_ids=tuple(sorted(blocked_claim_ids)),
        execution_fingerprint=execution_fingerprint,
        authority_state_fingerprint=authority_state_fingerprint,
        pipeline_source_binding_count=len(runtime_binding_hashes),
        tokenizer_probe=probe,
        errors=tuple(errors),
    )


def probe_runtime_tokenizers(
    *,
    repository_root: Path | None = None,
    query_tokenize: Callable[[str], set[str]] | None = None,
    evidence_tokenize: Callable[[str], set[str]] | None = None,
    query_tokenizer_id: str | None = "ascii_identifier_regex_v1",
    evidence_tokenizer_id: str | None = "ascii_identifier_regex_v1",
) -> TokenizerProbe:
    """Classify runtime tokenizer behavior with safe ASCII and CJK canaries."""

    runtime_probe_valid = True
    query_ascii: set[str] = set()
    evidence_ascii: set[str] = set()
    query_cjk: set[str] = set()
    evidence_cjk: set[str] = set()
    if query_tokenize is None and evidence_tokenize is None:
        resolved_root = repository_root or Path(__file__).resolve().parents[2]
        probe_script = "\n".join(
            (
                "import importlib, json, os, sys, types",
                "from pathlib import Path",
                "root = Path(os.environ['FORMOWL_METHODOLOGY_PROBE_ROOT'])",
                "package = types.ModuleType('formowl_mail')",
                "package.__path__ = [str(root / 'python' / 'formowl_mail')]",
                "package.__package__ = 'formowl_mail'",
                "sys.modules['formowl_mail'] = package",
                "query = importlib.import_module('formowl_mail.query')",
                "evidence = importlib.import_module('formowl_mail.evidence')",
                "def capture(module, value):",
                "    result = module._tokenize(value)",
                "    if type(result) is not set or any(type(item) is not str for item in result):",
                "        raise TypeError('invalid tokenizer result')",
                "    return sorted(result)",
                "payload = {",
                "    'valid': True,",
                "    'query_tokenizer_id': getattr(query, 'MAIL_TOKENIZER_ID', None),",
                "    'evidence_tokenizer_id': getattr(evidence, 'MAIL_TOKENIZER_ID', None),",
                f"    'query_ascii': capture(query, {_ASCII_PROBE!r}),",
                f"    'evidence_ascii': capture(evidence, {_ASCII_PROBE!r}),",
                f"    'query_cjk': capture(query, {_CJK_PROBE!r}),",
                f"    'evidence_cjk': capture(evidence, {_CJK_PROBE!r}),",
                "}",
                "print(json.dumps(payload, ensure_ascii=True, sort_keys=True))",
            )
        )
        environment = os.environ.copy()
        python_paths = [str(resolved_root / "python")]
        installed_python_root = Path(__file__).resolve().parents[1]
        if installed_python_root != resolved_root / "python":
            python_paths.append(str(installed_python_root))
        if environment.get("PYTHONPATH"):
            python_paths.append(environment["PYTHONPATH"])
        environment["PYTHONPATH"] = os.pathsep.join(python_paths)
        environment["FORMOWL_METHODOLOGY_PROBE_ROOT"] = str(resolved_root)
        completed: subprocess.CompletedProcess[str] | None = None
        try:
            completed = subprocess.run(
                [sys.executable, "-c", probe_script],
                cwd=resolved_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            payload = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            payload = {}
        if (
            completed is None
            or completed.returncode != 0
            or not isinstance(payload, dict)
            or set(payload)
            != {
                "valid",
                "query_tokenizer_id",
                "evidence_tokenizer_id",
                "query_ascii",
                "evidence_ascii",
                "query_cjk",
                "evidence_cjk",
            }
            or payload.get("valid") is not True
        ):
            runtime_probe_valid = False
        else:
            query_tokenizer_id = payload.get("query_tokenizer_id")
            evidence_tokenizer_id = payload.get("evidence_tokenizer_id")
            token_lists = (
                payload.get("query_ascii"),
                payload.get("evidence_ascii"),
                payload.get("query_cjk"),
                payload.get("evidence_cjk"),
            )
            if any(
                not isinstance(items, list)
                or len(set(items)) != len(items)
                or any(type(item) is not str for item in items)
                for items in token_lists
            ):
                runtime_probe_valid = False
            else:
                query_ascii, evidence_ascii, query_cjk, evidence_cjk = (
                    set(items) for items in token_lists
                )
    elif query_tokenize is None or evidence_tokenize is None:
        runtime_probe_valid = False
    else:
        try:
            raw_tokens = (
                query_tokenize(_ASCII_PROBE),
                evidence_tokenize(_ASCII_PROBE),
                query_tokenize(_CJK_PROBE),
                evidence_tokenize(_CJK_PROBE),
            )
        except Exception:
            runtime_probe_valid = False
        else:
            if any(
                type(tokens) is not set or any(type(token) is not str for token in tokens)
                for tokens in raw_tokens
            ):
                runtime_probe_valid = False
            else:
                query_ascii, evidence_ascii, query_cjk, evidence_cjk = raw_tokens

    ascii_support = (
        runtime_probe_valid
        and query_ascii == _EXPECTED_ASCII_PROBE_TOKENS
        and evidence_ascii == _EXPECTED_ASCII_PROBE_TOKENS
    )
    cjk_support = (
        runtime_probe_valid
        and query_cjk == _EXPECTED_TARGET_CJK_PROBE_TOKENS
        and evidence_cjk == _EXPECTED_TARGET_CJK_PROBE_TOKENS
    )
    if (
        query_tokenizer_id == evidence_tokenizer_id == "ascii_identifier_regex_v1"
        and ascii_support
        and query_cjk == evidence_cjk == set()
    ):
        tokenizer_id = "ascii_identifier_regex_v1"
    elif (
        query_tokenizer_id == evidence_tokenizer_id == _FROZEN_TARGET_PIPELINE["tokenizer_id"]
        and ascii_support
        and cjk_support
    ):
        tokenizer_id = _FROZEN_TARGET_PIPELINE["tokenizer_id"]
    else:
        tokenizer_id = "unregistered_runtime_tokenizer"
    return TokenizerProbe(
        tokenizer_id=tokenizer_id,
        query_tokenizer_id=(query_tokenizer_id if isinstance(query_tokenizer_id, str) else None),
        evidence_tokenizer_id=(
            evidence_tokenizer_id if isinstance(evidence_tokenizer_id, str) else None
        ),
        runtime_probe_valid=runtime_probe_valid,
        ascii_identifier_support=ascii_support,
        cjk_support=cjk_support,
        query_token_count=len(query_ascii) + len(query_cjk),
        evidence_token_count=len(evidence_ascii) + len(evidence_cjk),
    )


def _validate_gates(
    value: Any,
    errors: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    if not isinstance(value, list):
        errors.append("required_gates_must_be_list")
        return [], set()
    gates: list[dict[str, Any]] = []
    seen: set[str] = set()
    blocking: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append("required_gate_must_be_object")
            continue
        _require_exact_keys(item, _GATE_KEYS, f"required_gates[{index}]", errors)
        gate_id = _string(item.get("gate_id"), f"required_gates[{index}].gate_id", errors)
        gate_status = item.get("status")
        if gate_status not in {"passed", "blocked"}:
            errors.append("invalid_required_gate_status")
        reason_code = _string(
            item.get("reason_code"),
            f"required_gates[{index}].reason_code",
            errors,
        )
        evidence = _string_list(
            item.get("evidence"),
            f"required_gates[{index}].evidence",
            errors,
        )
        if gate_id:
            if gate_id in seen:
                errors.append("duplicate_required_gate_id")
            seen.add(gate_id)
            if gate_status == "blocked":
                blocking.add(gate_id)
        if gate_status == "passed" and (not reason_code or not evidence):
            errors.append("passed_gate_requires_reason_and_evidence")
        gates.append(item)
    if seen != _REQUIRED_GATE_IDS:
        errors.append("required_methodology_gate_set_mismatch")
    return gates, blocking


def _methodology_fingerprints(
    *,
    authority_id: str | None,
    updated_at: str | None,
    status: str | None,
    target: dict[str, Any],
    current: dict[str, Any],
    gates: list[dict[str, Any]],
    claim_policy: dict[str, Any],
    probe: TokenizerProbe,
    runtime_binding_hashes: dict[str, str],
) -> tuple[str, str]:
    execution_identity = json.dumps(
        {
            "authority_id": authority_id,
            "target_pipeline": target,
            "current_runtime": current,
            "tokenizer_probe": probe.to_dict(),
            "runtime_binding_hashes": runtime_binding_hashes,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    authority_state = json.dumps(
        {
            "authority_id": authority_id,
            "updated_at": updated_at,
            "status": status,
            "required_gates": gates,
            "claim_policy": claim_policy,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return (
        f"sha256:{hashlib.sha256(execution_identity).hexdigest()}",
        f"sha256:{hashlib.sha256(authority_state).hexdigest()}",
    )


def _validate_pipeline_source_bindings(
    repository_root: Path,
    *,
    tokenizer_id: str,
    runtime_probe_valid: bool,
    errors: list[str],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    source_paths = set(_PIPELINE_SOURCE_BINDINGS)
    for relative_root in _PIPELINE_SOURCE_ROOTS:
        source_root = repository_root / relative_root
        if not source_root.is_dir():
            errors.append("pipeline_source_binding_unreadable")
            continue
        source_paths.update(
            path.relative_to(repository_root)
            for path in source_root.rglob("*.py")
            if path.is_file()
        )
    expected_helper = _TOKENIZER_BINDING_HELPERS.get(tokenizer_id)
    for relative_path in sorted(source_paths):
        source_path = _resolve_repo_regular_file(repository_root, relative_path)
        if source_path is None:
            errors.append("pipeline_source_binding_unreadable")
            continue
        try:
            source = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append("pipeline_source_binding_unreadable")
            continue
        hashes[relative_path.as_posix()] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        if relative_path not in _TOKENIZER_RUNTIME_BINDINGS:
            continue
        if expected_helper is None and not runtime_probe_valid:
            # A runtime that cannot be imported or classified is already
            # invalid. Do not add a misleading binding-drift error on top of
            # the fail-closed probe failure.
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            errors.append("runtime_tokenizer_binding_drift")
            continue
        if not _has_expected_tokenizer_binding(
            tree,
            expected_helpers=expected_helper,
            expected_callers=_TOKENIZER_RUNTIME_CALLERS[relative_path],
        ):
            errors.append("runtime_tokenizer_binding_drift")
    return hashes


def _validate_gate_evidence_paths(
    repository_root: Path,
    gates: list[dict[str, Any]],
    errors: list[str],
) -> None:
    for gate in gates:
        for value in gate.get("evidence", []):
            if not isinstance(value, str):
                continue
            relative_path = Path(value)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                errors.append("methodology_gate_evidence_path_must_be_repo_relative")
                continue
            if _resolve_repo_regular_file(repository_root, relative_path) is None:
                errors.append("methodology_gate_evidence_path_not_regular_repo_file")


def _validate_passed_gate_evidence(
    *,
    repository_root: Path,
    authority_id: str | None,
    gates: list[dict[str, Any]],
    execution_fingerprint: str,
    errors: list[str],
) -> None:
    is_sha256 = (  # noqa: E731
        lambda value: (
            isinstance(value, str)
            and len(value) == 71
            and value.startswith("sha256:")
            and all(character in "0123456789abcdef" for character in value[7:])
        )
    )
    is_nonnegative_int = lambda value: type(value) is int and value >= 0  # noqa: E731
    is_positive_int = lambda value: type(value) is int and value > 0  # noqa: E731
    for gate in gates:
        gate_id = gate.get("gate_id")
        if gate.get("status") != "passed" or gate_id not in _EXECUTABLE_EVIDENCE_GATE_IDS:
            continue
        evidence_valid = False
        for value in gate.get("evidence", []):
            if not isinstance(value, str) or not value.endswith(".json"):
                continue
            path = _resolve_repo_regular_file(repository_root, Path(value))
            if path is None:
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or set(payload) != _GATE_EVIDENCE_KEYS:
                continue
            if not (
                payload.get("artifact_id") == _GATE_EVIDENCE_ARTIFACT_ID
                and payload.get("authority_id") == authority_id
                and payload.get("gate_id") == gate_id
                and payload.get("execution_fingerprint") == execution_fingerprint
                and payload.get("validator_id") == _GATE_VALIDATOR_IDS[gate_id]
                and payload.get("status") == "passed"
            ):
                continue

            source_manifest_value = payload.get("source_manifest_path")
            result_artifact_value = payload.get("result_artifact_path")
            if not isinstance(source_manifest_value, str) or not source_manifest_value:
                continue
            if not isinstance(result_artifact_value, str) or not result_artifact_value:
                continue
            source_manifest_relative = Path(source_manifest_value)
            result_artifact_relative = Path(result_artifact_value)
            if (
                source_manifest_relative.is_absolute()
                or ".." in source_manifest_relative.parts
                or result_artifact_relative.is_absolute()
                or ".." in result_artifact_relative.parts
            ):
                continue
            source_manifest_path = _resolve_repo_regular_file(
                repository_root,
                source_manifest_relative,
            )
            result_artifact_path = _resolve_repo_regular_file(
                repository_root,
                result_artifact_relative,
            )
            if source_manifest_path is None or result_artifact_path is None:
                continue
            try:
                source_manifest_bytes = source_manifest_path.read_bytes()
                result_artifact_bytes = result_artifact_path.read_bytes()
            except OSError:
                continue
            source_manifest_sha256 = f"sha256:{hashlib.sha256(source_manifest_bytes).hexdigest()}"
            result_artifact_sha256 = f"sha256:{hashlib.sha256(result_artifact_bytes).hexdigest()}"
            if not (
                is_sha256(payload.get("source_manifest_sha256"))
                and payload.get("source_manifest_sha256") == source_manifest_sha256
                and is_sha256(payload.get("result_artifact_sha256"))
                and payload.get("result_artifact_sha256") == result_artifact_sha256
            ):
                continue
            try:
                source_manifest = json.loads(source_manifest_bytes)
                result_artifact = json.loads(result_artifact_bytes)
            except (UnicodeError, json.JSONDecodeError):
                continue
            if (
                not isinstance(source_manifest, dict)
                or set(source_manifest) != _SOURCE_MANIFEST_KEYS
                or source_manifest.get("artifact_id") != _SOURCE_MANIFEST_ARTIFACT_ID
                or source_manifest.get("execution_fingerprint") != execution_fingerprint
                or source_manifest.get("source_kind") != "real_source"
                or not is_positive_int(source_manifest.get("source_count"))
                or not is_positive_int(source_manifest.get("source_item_count"))
                or not is_sha256(source_manifest.get("case_manifest_sha256"))
                or not is_sha256(source_manifest.get("configuration_manifest_sha256"))
                or not is_sha256(source_manifest.get("package_lock_sha256"))
            ):
                continue
            source_hashes = source_manifest.get("source_hashes")
            model_artifact_hashes = source_manifest.get("model_artifact_hashes")
            if (
                not isinstance(source_hashes, list)
                or len(source_hashes) != source_manifest.get("source_count")
                or len(set(source_hashes)) != len(source_hashes)
                or any(not is_sha256(item) for item in source_hashes)
                or not isinstance(model_artifact_hashes, list)
                or not model_artifact_hashes
                or len(set(model_artifact_hashes)) != len(model_artifact_hashes)
                or any(not is_sha256(item) for item in model_artifact_hashes)
            ):
                continue
            if (
                not isinstance(result_artifact, dict)
                or set(result_artifact) != _GATE_RESULT_KEYS[gate_id]
                or result_artifact.get("artifact_id") != _GATE_RESULT_ARTIFACT_IDS[gate_id]
                or result_artifact.get("execution_fingerprint") != execution_fingerprint
                or result_artifact.get("source_manifest_sha256") != source_manifest_sha256
                or result_artifact.get("status") != "passed"
            ):
                continue

            if gate_id == "source_completeness_compared_with_raw_oracle":
                raw_count = result_artifact.get("raw_source_unit_count")
                observed_count = result_artifact.get("emitted_observation_unit_count")
                redacted_count = result_artifact.get("policy_redacted_unit_count")
                unexplained_count = result_artifact.get("unexplained_loss_unit_count")
                loss_taxonomy = result_artifact.get("loss_taxonomy_counts")
                evidence_valid = (
                    is_positive_int(raw_count)
                    and is_nonnegative_int(observed_count)
                    and is_nonnegative_int(redacted_count)
                    and is_nonnegative_int(unexplained_count)
                    and observed_count + redacted_count + unexplained_count == raw_count
                    and unexplained_count == 0
                    and isinstance(loss_taxonomy, dict)
                    and all(
                        isinstance(key, str) and key and is_nonnegative_int(count)
                        for key, count in loss_taxonomy.items()
                    )
                    and sum(loss_taxonomy.values()) == unexplained_count
                )
            elif gate_id == "evaluation_reports_bind_execution_fingerprint":
                report_count = result_artifact.get("report_count")
                bound_count = result_artifact.get("bound_report_count")
                unbound_count = result_artifact.get("unbound_report_count")
                report_hashes = result_artifact.get("report_hashes")
                evidence_valid = (
                    is_positive_int(report_count)
                    and bound_count == report_count
                    and unbound_count == 0
                    and isinstance(report_hashes, list)
                    and len(report_hashes) == report_count
                    and len(set(report_hashes)) == len(report_hashes)
                    and all(is_sha256(item) for item in report_hashes)
                )
            elif gate_id == "same_pipeline_real_source_ablation":
                arm_ids = result_artifact.get("arm_ids")
                case_count = result_artifact.get("case_count")
                result_hashes_by_arm = result_artifact.get("result_hashes_by_arm")
                evidence_valid = (
                    isinstance(arm_ids, list)
                    and set(arm_ids) == _ABLATION_ARM_IDS
                    and len(arm_ids) == len(_ABLATION_ARM_IDS)
                    and is_positive_int(case_count)
                    and case_count >= _MINIMUM_REAL_USER_CASE_COUNT
                    and result_artifact.get("completed_case_count") == case_count
                    and result_artifact.get("adjudicated_case_count") == case_count
                    and result_artifact.get("same_source_manifest") is True
                    and result_artifact.get("same_case_manifest") is True
                    and result_artifact.get("same_evaluation_policy") is True
                    and isinstance(result_hashes_by_arm, dict)
                    and set(result_hashes_by_arm) == _ABLATION_ARM_IDS
                    and all(is_sha256(item) for item in result_hashes_by_arm.values())
                )
            elif gate_id == "real_user_end_answer_acceptance":
                case_count = result_artifact.get("case_count")
                answerable_count = result_artifact.get("answerable_case_count")
                correct_count = result_artifact.get("correct_answer_count")
                citation_count = result_artifact.get("citation_supported_correct_count")
                denial_count = result_artifact.get("permission_denial_case_count")
                denial_pass_count = result_artifact.get("permission_denial_pass_count")
                if (
                    result_artifact.get("acceptance_profile_id")
                    != _END_ANSWER_ACCEPTANCE_PROFILE_ID
                    or not is_positive_int(case_count)
                    or case_count < _MINIMUM_REAL_USER_CASE_COUNT
                    or result_artifact.get("adjudicated_case_count") != case_count
                    or not is_positive_int(answerable_count)
                    or not is_nonnegative_int(correct_count)
                    or correct_count > answerable_count
                    or not is_nonnegative_int(citation_count)
                    or citation_count > correct_count
                    or not is_positive_int(denial_count)
                    or denial_pass_count != denial_count
                ):
                    evidence_valid = False
                else:
                    accuracy_ppm = correct_count * 1_000_000 // answerable_count
                    citation_support_ppm = (
                        citation_count * 1_000_000 // correct_count if correct_count else 0
                    )
                    evidence_valid = (
                        result_artifact.get("observed_accuracy_ppm") == accuracy_ppm
                        and result_artifact.get("observed_citation_support_ppm")
                        == citation_support_ppm
                        and accuracy_ppm >= _MINIMUM_END_ANSWER_ACCURACY_PPM
                        and citation_support_ppm == _REQUIRED_CITATION_SUPPORT_PPM
                    )
            if evidence_valid:
                validator = _GATE_EXECUTABLE_VALIDATORS.get(gate_id)
                if validator is None:
                    errors.append(f"passed_gate_executable_validator_unavailable:{gate_id}")
                    evidence_valid = False
                    continue
                try:
                    evidence_valid = validator(
                        repository_root=repository_root,
                        source_manifest_path=source_manifest_path,
                        result_artifact_path=result_artifact_path,
                        source_manifest=source_manifest,
                        result_artifact=result_artifact,
                        execution_fingerprint=execution_fingerprint,
                    )
                except Exception:  # pragma: no cover - fail-closed plugin boundary
                    evidence_valid = False
                if evidence_valid:
                    break
        if not evidence_valid:
            errors.append(f"passed_gate_missing_validated_evidence:{gate_id}")


def _resolve_repo_regular_file(
    repository_root: Path,
    relative_path: Path,
) -> Path | None:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None
    try:
        resolved_root = repository_root.resolve(strict=True)
    except OSError:
        return None
    candidate = resolved_root
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink():
            return None
    try:
        resolved_candidate = candidate.resolve(strict=True)
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return resolved_candidate if resolved_candidate.is_file() else None


def _gate_status(gates: list[dict[str, Any]], gate_id: str) -> str | None:
    for gate in gates:
        if gate.get("gate_id") == gate_id:
            value = gate.get("status")
            return value if isinstance(value, str) else None
    return None


def _has_expected_tokenizer_binding(
    tree: ast.AST,
    *,
    expected_helpers: tuple[str, ...] | None,
    expected_callers: set[str],
) -> bool:
    if not isinstance(tree, ast.Module) or not expected_helpers:
        return False
    canonical_helpers: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            bound_name = alias.asname or alias.name
            if bound_name not in expected_helpers:
                continue
            if (
                node.module == "formowl_core"
                and alias.name == bound_name
                and alias.asname is None
            ):
                canonical_helpers.append(bound_name)
            else:
                return False
    if len(canonical_helpers) != 1:
        return False
    expected_helper = canonical_helpers[0]
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name == expected_helper
        ):
            return False
        if (
            isinstance(node, ast.Name)
            and node.id in {expected_helper, "_tokenize"}
            and isinstance(node.ctx, (ast.Store, ast.Del))
        ):
            return False
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound_name = alias.asname or alias.name.split(".")[0]
                if bound_name == expected_helper and not (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "formowl_core"
                    and alias.name == expected_helper
                    and alias.asname is None
                ):
                    return False
    tokenizer_functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_tokenize"
    ]
    if len(tokenizer_functions) != 1:
        return False
    tokenizer_function = tokenizer_functions[0]
    if (
        len(tokenizer_function.args.args) != 1
        or tokenizer_function.args.args[0].arg != "value"
        or tokenizer_function.args.posonlyargs
        or tokenizer_function.args.kwonlyargs
        or tokenizer_function.args.vararg is not None
        or tokenizer_function.args.kwarg is not None
        or len(tokenizer_function.body) != 1
    ):
        return False
    statement = tokenizer_function.body[0]
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    if not (
        isinstance(call.func, ast.Name)
        and call.func.id == expected_helper
        and len(call.args) == 1
        and isinstance(call.args[0], ast.Name)
        and call.args[0].id == "value"
        and not call.keywords
    ):
        return False
    callers = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in expected_callers
    }
    if set(callers) != expected_callers:
        return False
    local_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for caller_name in callers:
        pending = [caller_name]
        visited: set[str] = set()
        reaches_tokenizer = False
        while pending:
            function_name = pending.pop()
            if function_name in visited:
                continue
            visited.add(function_name)
            function = local_functions.get(function_name)
            if function is None:
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id == "_tokenize":
                    reaches_tokenizer = True
                    break
                if node.func.id in local_functions:
                    pending.append(node.func.id)
            if reaches_tokenizer:
                break
        if not reaches_tokenizer:
            return False
    return True


def _contains_cjk_token(tokens: set[str]) -> bool:
    return any(any("\u3400" <= char <= "\u9fff" for char in token) for token in tokens)


def _object(value: Any, field_name: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{field_name}_must_be_object")
        return {}
    return value


def _string(value: Any, field_name: str, errors: list[str]) -> str | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field_name}_must_be_nonempty_string")
        return None
    return value


def _string_list(value: Any, field_name: str, errors: list[str]) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        errors.append(f"{field_name}_must_be_nonempty_string_list")
        return []
    if len(set(value)) != len(value):
        errors.append(f"{field_name}_must_not_contain_duplicates")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    field_name: str,
    errors: list[str],
) -> None:
    if set(value) != expected:
        errors.append(f"{field_name}_key_set_mismatch")


def _invalid_result(probe: TokenizerProbe, error: str) -> MethodologyAuthorityResult:
    return MethodologyAuthorityResult(
        authority_valid=False,
        methodology_ready=False,
        authority_id=None,
        status=None,
        target_method_id=None,
        target_tokenizer_id=None,
        current_method_id=None,
        current_tokenizer_id=None,
        blocking_gate_ids=(),
        blocked_claim_ids=(),
        execution_fingerprint=None,
        authority_state_fingerprint=None,
        pipeline_source_binding_count=0,
        tokenizer_probe=probe,
        errors=(error,),
    )


__all__ = [
    "AUTHORITY_RELATIVE_PATH",
    "MethodologyAuthorityResult",
    "TokenizerProbe",
    "check_methodology_authority",
    "probe_runtime_tokenizers",
]
