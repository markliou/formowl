"""Fail-closed authority checks for FormOwl methodology and runtime alignment."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
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
    "current_runtime_has_production_chinese_tokenization",
    "historical_real_pst_results_compare_the_current_target_method",
    "kg_outperforms_kg_plus_ontology",
    "kg_plus_ontology_outperforms_kg_on_real_sources",
    "methodology_ready_for_quality_uat",
    "methodology_objective_complete",
}
_REQUIRED_ALLOWED_CLAIM_IDS = {
    "current_runtime_implements_target_method",
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
_EXPECTED_TARGET_CJK_PROBE_TOKENS = {"查詢", "交期", "產地"}
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
    "ascii_identifier_regex_v1": "ascii_identifier_regex_tokens",
    _FROZEN_TARGET_PIPELINE[
        "tokenizer_id"
    ]: "jieba_sentencepiece_frozen_profile_candidate_admission_tokens",
}
_EXPECTED_RUNTIME_METHOD_BINDING = {
    "method_id": _FROZEN_TARGET_PIPELINE["method_id"],
    "normal_entrypoint": "run_authorized_semantic_mail_query",
    "authorization_order": "permission_before_candidate_materialization",
    "lexical_dense_path": "bm25_pinned_multilingual_e5_same_profile_v1",
    "typed_router": "semantic_query_plan_fail_closed_v1",
    "entity_path": "source_backed_entity_matching_v1",
    "candidate_graph_path": "source_backed_mail_candidate_graph_v1",
    "ontology_path": "capped_soft_additive_ontology_v1",
    "exact_path": "deterministic_authorized_inventory_coverage_v1",
    "cited_result_path": "governed_authorized_observation_citations_v1",
    "legacy_hard_gate_default": False,
    "fallback_policy": "fail_closed_no_ascii_hash_random_or_diagnostic_fallback_v1",
}
_RUNTIME_METHOD_BINDING_FILES = {
    "hybrid": Path("python/formowl_mail/hybrid.py"),
    "semantic_plan": Path("python/formowl_mail/semantic_plan.py"),
    "exact": Path("python/formowl_mail/exact.py"),
    "answer": Path("python/formowl_mail/answer.py"),
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
    "schema_version",
    "authority_id",
    "gate_id",
    "execution_fingerprint",
    "validator_id",
    "source_manifest_path",
    "source_manifest_sha256",
    "result_artifact_path",
    "result_artifact_sha256",
    "dependency_manifest_path",
    "dependency_manifest_sha256",
    "dependency_manifest_fingerprint",
    "dependency_count",
    "execution_binding",
    "status",
    "evidence_classification",
    "promotion_status",
    "envelope_fingerprint",
}
_GATE_EVIDENCE_ARTIFACT_ID = "formowl_methodology_gate_evidence_v3"
_GATE_EVIDENCE_SCHEMA_VERSION = 1
_GATE_EVIDENCE_FINGERPRINT_FIELD = "envelope_fingerprint"
_GATE_DEPENDENCY_MANIFEST_ARTIFACT_ID = "formowl_methodology_gate_dependency_manifest_v1"
_GATE_DEPENDENCY_MANIFEST_KEYS = {
    "artifact_id",
    "gate_id",
    "execution_fingerprint",
    "source_manifest_path",
    "source_manifest_sha256",
    "result_artifact_path",
    "result_artifact_sha256",
    "dependencies",
    "manifest_fingerprint",
}
_GATE_DEPENDENCY_ENTRY_KEYS = {
    "role",
    "path",
    "artifact_id",
    "byte_sha256",
    "internal_fingerprint_field",
    "internal_fingerprint",
}
_GATE_EXECUTION_BINDING_REFERENCE_KEYS = {
    "role",
    "path",
    "byte_sha256",
    "bundle_fingerprint",
    "complete_execution_fingerprint",
}
_GATE_DEPENDENCY_ARTIFACT_KEYS = {
    "artifact_id",
    "gate_id",
    "execution_fingerprint",
    "source_manifest_sha256",
    "status",
    "evidence_classification",
    "dependency_paths",
    "payload",
    "artifact_fingerprint",
}
_SOURCE_ROOT_DEPENDENCY_ARTIFACT_KEYS = {
    "artifact_id",
    "dependency_paths",
    "payload",
    "artifact_fingerprint",
}
_GATE_DEPENDENCY_INTERNAL_FINGERPRINT_FIELD = "artifact_fingerprint"
_EXECUTION_BINDING_DEPENDENCY_ROLE = "execution_binding_bundle"
_EXECUTION_BINDING_BUNDLE_ARTIFACT_ID = "formowl_issue56_execution_fingerprint_acceptance_bundle_v1"
_EXECUTION_BINDING_ARTIFACT_ID = "formowl_issue56_complete_execution_binding_v1"
_EXECUTION_BINDING_SCHEMA_VERSION = 1
_EXECUTION_BINDING_BUNDLE_KEYS = {
    "artifact_id",
    "schema_version",
    "status",
    "run_binding_fingerprint",
    "source_binding_fingerprint",
    "execution_fingerprint",
    "execution_binding_status",
    "execution_binding",
    "component_artifact_fingerprints",
    "bound_fingerprints",
    "counts",
    "statuses",
    "blocking_status_ids",
    "blocking_status_fingerprint",
    "bundle_fingerprint",
}
_EXECUTION_BINDING_KEYS = {
    "artifact_id",
    "schema_version",
    "source_binding_fingerprint",
    "source_completeness_report_sha256",
    "source_completeness_report_fingerprint",
    "bound_fingerprints",
}
_EXECUTION_BINDING_COMPONENT_KEYS = {
    "answer",
    "authority",
    "code",
    "evaluation",
    "graph_ontology",
    "image",
    "lexical_index",
    "source",
}
_EXECUTION_IDENTITY_BOUND_FINGERPRINT_KEYS = {
    "answer_budget",
    "answer_model",
    "answer_prompt",
    "authority_execution",
    "authorized_identifier_mention_set",
    "code_commit",
    "code_tree",
    "code_tree_scope",
    "complete_identifier_mention_batch",
    "complete_identifier_mention_set",
    "complete_identifier_resolution",
    "dense_profile",
    "evaluator",
    "graph_adapter",
    "graph_artifact",
    "graph_identifier_resolution_set",
    "graph_relation_type_set",
    "image_attestor",
    "image_id",
    "image_metadata",
    "index",
    "lexical_profile",
    "ontology_artifact",
    "ontology_target",
    "runtime_component",
    "runtime_method",
    "script",
    "selected_identifier_mention_batch",
    "selected_identifier_resolution",
    "source_graph_policy",
    "source_identifier_adapter",
    "source_identifier_candidate_artifact",
    "source_identifier_candidate_binding",
    "source_identifier_candidate_schema",
    "source_identifier_extraction_policy",
    "source_identifier_identity_scope",
    "source_identifier_identity_scope_attestation",
    "source_identifier_identity_scope_attestation_bytes",
    "source_identifier_identity_scope_binding",
    "source_identifier_identity_scope_graph_binding_set",
    "source_identifier_identity_scope_mode",
    "source_identifier_identity_scope_policy",
    "source_identifier_mode_approval",
    "source_identifier_operator_approval",
    "source_identifier_resolution_policy",
    "source_inventory",
    "source_snapshot",
}
_GATE_DEPENDENCY_MANIFEST_FINGERPRINT_FIELD = "manifest_fingerprint"
_SOURCE_MANIFEST_FINGERPRINT_FIELD = "manifest_fingerprint"
_GATE_RESULT_FINGERPRINT_FIELD = "result_fingerprint"
_OPAQUE_DEPENDENCY_ROLES = {
    "model_artifact",
    "package_lock",
    "source_item",
}
_COMMON_DEPENDENCY_ARTIFACT_IDS = {
    "case_manifest": "formowl_methodology_case_manifest_dependency_v1",
    "configuration_manifest": "formowl_methodology_configuration_manifest_dependency_v1",
    _EXECUTION_BINDING_DEPENDENCY_ROLE: _EXECUTION_BINDING_BUNDLE_ARTIFACT_ID,
    "source_inventory_manifest": "formowl_methodology_source_inventory_dependency_v1",
}
_GATE_DEPENDENCY_ARTIFACT_IDS = {
    "raw_source_oracle_manifest": "formowl_methodology_raw_source_oracle_dependency_v1",
    "observation_reconciliation_report": (
        "formowl_methodology_observation_reconciliation_dependency_v1"
    ),
    "evaluation_report_index": "formowl_methodology_evaluation_report_index_dependency_v1",
    "evaluation_report": "formowl_methodology_evaluation_report_dependency_v1",
    "ablation_arm_result": "formowl_methodology_ablation_arm_result_dependency_v1",
    "final_answer_acceptance_report": ("formowl_methodology_final_answer_acceptance_dependency_v1"),
}
_PRODUCTION_CASE_SCOPES = {
    "evaluation",
    "independent_holdout",
    "transfer_holdout",
    "combined_independent_acceptance",
}
_DISALLOWED_EVIDENCE_STATES = {
    "blocked",
    "diagnostic",
    "diagnostic_only",
    "failed",
    "partial",
    "preflight",
    "preflight_only",
}
_DISALLOWED_EVIDENCE_PATH_TOKENS = {
    ".test-tmp",
    "blocked",
    "diagnostic",
    "preflight",
    "tmp",
}
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
    "manifest_fingerprint",
}
_SOURCE_MANIFEST_ARTIFACT_ID = "formowl_methodology_source_manifest_v1"
_RESULT_COMMON_KEYS = {
    "artifact_id",
    "execution_fingerprint",
    "source_manifest_sha256",
    "status",
    "result_fingerprint",
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
    runtime_dependencies_available: bool
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
            "runtime_dependencies_available": self.runtime_dependencies_available,
            "ascii_identifier_support": self.ascii_identifier_support,
            "cjk_support": self.cjk_support,
            "query_token_count": self.query_token_count,
            "evidence_token_count": self.evidence_token_count,
        }


@dataclass(frozen=True)
class RuntimePipelineProbe:
    method_id: str | None
    method_fingerprint: str | None
    runtime_probe_valid: bool
    normal_entrypoint_bound: bool
    typed_plan_bound: bool
    strong_rag_bound: bool
    entity_graph_bound: bool
    soft_ontology_bound: bool
    exact_executor_bound: bool
    cited_answer_bound: bool
    legacy_or_ascii_fallback_absent: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id,
            "method_fingerprint": self.method_fingerprint,
            "runtime_probe_valid": self.runtime_probe_valid,
            "normal_entrypoint_bound": self.normal_entrypoint_bound,
            "typed_plan_bound": self.typed_plan_bound,
            "strong_rag_bound": self.strong_rag_bound,
            "entity_graph_bound": self.entity_graph_bound,
            "soft_ontology_bound": self.soft_ontology_bound,
            "exact_executor_bound": self.exact_executor_bound,
            "cited_answer_bound": self.cited_answer_bound,
            "legacy_or_ascii_fallback_absent": self.legacy_or_ascii_fallback_absent,
        }


@dataclass(frozen=True)
class MethodologyGateDependency:
    role: str
    relative_path: Path
    byte_sha256: str
    artifact_id: str | None
    payload: dict[str, Any] | None


@dataclass(frozen=True)
class MethodologyGateDependencyManifest:
    relative_path: Path
    manifest_fingerprint: str
    dependencies: tuple[MethodologyGateDependency, ...]

    def by_role(self, role: str) -> tuple[MethodologyGateDependency, ...]:
        return tuple(item for item in self.dependencies if item.role == role)


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
    runtime_pipeline_probe: RuntimePipelineProbe
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
            "runtime_pipeline_probe": self.runtime_pipeline_probe.to_dict(),
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
    runtime_pipeline_probe = probe_runtime_pipeline(repository_root=repository_root)
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

    dependency_deferred_target_probe = (
        current_tokenizer_id == _FROZEN_TARGET_PIPELINE["tokenizer_id"]
        and not probe.runtime_dependencies_available
        and not probe.runtime_probe_valid
    )
    if not probe.runtime_probe_valid and not dependency_deferred_target_probe:
        errors.append("runtime_tokenizer_probe_failed")
    if (
        probe.runtime_probe_valid
        and current_tokenizer_id
        and current_tokenizer_id != probe.tokenizer_id
    ):
        errors.append("runtime_tokenizer_id_drift")
    if (
        probe.runtime_probe_valid
        and type(declared_cjk_support) is bool
        and declared_cjk_support != probe.cjk_support
    ):
        errors.append("runtime_cjk_capability_drift")
    if current_method_id == _FROZEN_TARGET_PIPELINE["method_id"] and (
        not runtime_pipeline_probe.runtime_probe_valid
        or runtime_pipeline_probe.method_id != current_method_id
    ):
        errors.append("runtime_method_binding_drift")
    runtime_binding_hashes = _validate_pipeline_source_bindings(
        repository_root,
        tokenizer_id=(
            current_tokenizer_id if dependency_deferred_target_probe else probe.tokenizer_id
        ),
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
        if not probe.runtime_probe_valid or not probe.cjk_support:
            errors.append("passed_runtime_gate_requires_cjk_runtime_support")
        if (
            not runtime_pipeline_probe.runtime_probe_valid
            or runtime_pipeline_probe.method_id != target_values["method_id"]
        ):
            errors.append("passed_runtime_gate_requires_target_runtime_probe")
    if status == "ready":
        if current_ingestion_policy_id != target_values["ingestion_policy_id"]:
            errors.append("ready_authority_requires_target_ingestion_policy")
        if current_evaluation_policy_id != target_values["evaluation_policy_id"]:
            errors.append("ready_authority_requires_target_evaluation_policy")

    execution_fingerprint, authority_state_fingerprint = _methodology_fingerprints(
        authority_id=authority_id,
        updated_at=updated_at,
        status=status,
        target=target,
        current=current,
        gates=gates,
        claim_policy=claim_policy,
        probe=probe,
        runtime_pipeline_probe=runtime_pipeline_probe,
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
        runtime_pipeline_probe=runtime_pipeline_probe,
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
    runtime_dependencies_available = True
    query_ascii: set[str] = set()
    evidence_ascii: set[str] = set()
    query_cjk: set[str] = set()
    evidence_cjk: set[str] = set()
    if query_tokenize is None and evidence_tokenize is None:
        resolved_root = repository_root or Path(__file__).resolve().parents[2]
        query_tokenizer_id = None
        evidence_tokenizer_id = None
        runtime_dependencies_available = all(
            importlib.util.find_spec(package_name) is not None
            for package_name in ("jieba", "sentencepiece")
        )
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
        runtime_dependencies_available=runtime_dependencies_available,
        ascii_identifier_support=ascii_support,
        cjk_support=cjk_support,
        query_token_count=len(query_ascii) + len(query_cjk),
        evidence_token_count=len(evidence_ascii) + len(evidence_cjk),
    )


def probe_runtime_pipeline(
    *,
    repository_root: Path | None = None,
) -> RuntimePipelineProbe:
    """Verify the normal target-method call graph without loading model artifacts."""

    resolved_root = repository_root or Path(__file__).resolve().parents[2]
    sources: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    for name, relative_path in _RUNTIME_METHOD_BINDING_FILES.items():
        path = _resolve_repo_regular_file(resolved_root, relative_path)
        if path is None:
            return _invalid_runtime_pipeline_probe()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, UnicodeError, SyntaxError):
            return _invalid_runtime_pipeline_probe()
        sources[name] = source
        trees[name] = tree

    binding = _literal_module_assignment(
        trees["hybrid"],
        "_ISSUE56_TARGET_RUNTIME_METHOD_BINDING",
    )
    method_id_value = _literal_module_assignment(
        trees["hybrid"],
        "ISSUE56_TARGET_RUNTIME_METHOD_ID",
    )
    method_id = method_id_value if isinstance(method_id_value, str) else None
    method_fingerprint = _canonical_sha256(binding) if isinstance(binding, dict) else None
    entrypoint = _top_level_function(
        trees["hybrid"],
        "run_authorized_semantic_mail_query",
    )
    session_query = _class_method(
        trees["hybrid"],
        "AuthorizedSemanticMailSession",
        "query",
    )
    answer_renderer = _top_level_function(
        trees["answer"],
        "render_governed_evidence_answer",
    )
    normal_entrypoint_bound = (
        entrypoint is not None
        and _function_default_is_false(entrypoint, "legacy_hard_gate")
        and {
            "build_authorized_semantic_mail_session",
            "query",
        }.issubset(_called_function_names(entrypoint))
    )
    session_calls = _called_function_names(session_query)
    typed_plan_bound = (
        session_query is not None
        and "route_semantic_query" in session_calls
        and _function_default_is_true(session_query, "enable_entity_signal")
        and _function_default_is_true(session_query, "enable_graph_traversal")
        and _function_default_is_false(session_query, "legacy_hard_gate")
    )
    strong_rag_bound = session_query is not None and "query" in session_calls
    entity_graph_bound = (
        session_query is not None
        and "_semantic_evidence_scores" in session_calls
        and "_bounded_graph_traversal" in session_calls
        and _top_level_function(
            trees["hybrid"],
            "build_authorized_source_backed_effective_graph_view",
        )
        is not None
    )
    soft_ontology_bound = (
        "soft_core_supertypes_compatible" in sources["hybrid"]
        and "ontology_bonus_cap" in sources["hybrid"]
        and "legacy_ontology_hard_gate_negative_ablation" in sources["hybrid"]
    )
    exact_executor_bound = (
        session_query is not None
        and "execute_deterministic_exact_inventory" in session_calls
        and _top_level_function(
            trees["exact"],
            "execute_deterministic_exact_inventory",
        )
        is not None
        and "authorized_scope_complete" in sources["exact"]
    )
    cited_answer_bound = (
        answer_renderer is not None
        and "_semantic_citation_hashes" in _called_function_names(answer_renderer)
        and "_bounded_semantic_answer_citation_hashes" in session_calls
    )
    forbidden_runtime_references = (
        "DeterministicDiagnosticDenseEncoder",
        "ascii_identifier_regex_tokens",
        "build_ascii_identifier_regex_tokenizer_profile",
    )
    legacy_or_ascii_fallback_absent = (
        all(
            forbidden not in source
            for source in sources.values()
            for forbidden in forbidden_runtime_references
        )
        and normal_entrypoint_bound
        and typed_plan_bound
    )
    runtime_probe_valid = all(
        (
            binding == _EXPECTED_RUNTIME_METHOD_BINDING,
            method_id == _FROZEN_TARGET_PIPELINE["method_id"],
            normal_entrypoint_bound,
            typed_plan_bound,
            strong_rag_bound,
            entity_graph_bound,
            soft_ontology_bound,
            exact_executor_bound,
            cited_answer_bound,
            legacy_or_ascii_fallback_absent,
        )
    )
    return RuntimePipelineProbe(
        method_id=method_id,
        method_fingerprint=method_fingerprint,
        runtime_probe_valid=runtime_probe_valid,
        normal_entrypoint_bound=normal_entrypoint_bound,
        typed_plan_bound=typed_plan_bound,
        strong_rag_bound=strong_rag_bound,
        entity_graph_bound=entity_graph_bound,
        soft_ontology_bound=soft_ontology_bound,
        exact_executor_bound=exact_executor_bound,
        cited_answer_bound=cited_answer_bound,
        legacy_or_ascii_fallback_absent=legacy_or_ascii_fallback_absent,
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
    runtime_pipeline_probe: RuntimePipelineProbe,
    runtime_binding_hashes: dict[str, str],
) -> tuple[str, str]:
    execution_identity = json.dumps(
        {
            "authority_id": authority_id,
            "target_pipeline": target,
            "current_runtime": current,
            "tokenizer_probe": probe.to_dict(),
            "runtime_pipeline_probe": runtime_pipeline_probe.to_dict(),
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
        try:
            tree = ast.parse(source)
        except SyntaxError:
            errors.append("runtime_tokenizer_binding_drift")
            continue
        if not _has_expected_tokenizer_binding(
            tree,
            expected_helper=expected_helper,
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


def methodology_gate_dependency_manifest_path(result_artifact_path: Path) -> Path:
    """Return the required adjacent dependency manifest path for a gate result."""

    return result_artifact_path.with_name(f"{result_artifact_path.name}.dependencies.json")


def validate_methodology_gate_dependency_manifest(
    *,
    repository_root: Path,
    gate_id: str,
    source_manifest_path: Path,
    result_artifact_path: Path,
    source_manifest: dict[str, Any],
    result_artifact: dict[str, Any],
    execution_fingerprint: str,
) -> bool:
    """Validate and dereference a production gate's complete dependency manifest."""

    return (
        _load_methodology_gate_dependency_manifest(
            repository_root=repository_root,
            gate_id=gate_id,
            source_manifest_path=source_manifest_path,
            result_artifact_path=result_artifact_path,
            source_manifest=source_manifest,
            result_artifact=result_artifact,
            execution_fingerprint=execution_fingerprint,
        )
        is not None
    )


def _load_methodology_gate_dependency_manifest(
    *,
    repository_root: Path,
    gate_id: str,
    source_manifest_path: Path,
    result_artifact_path: Path,
    source_manifest: dict[str, Any],
    result_artifact: dict[str, Any],
    execution_fingerprint: str,
) -> MethodologyGateDependencyManifest | None:
    if gate_id not in _EXECUTABLE_EVIDENCE_GATE_IDS:
        return None
    source_manifest_relative = _repo_relative_path(
        repository_root,
        source_manifest_path,
    )
    result_artifact_relative = _repo_relative_path(
        repository_root,
        result_artifact_path,
    )
    if (
        source_manifest_relative is None
        or result_artifact_relative is None
        or not _is_safe_production_dependency_path(source_manifest_relative)
        or not _is_safe_production_dependency_path(result_artifact_relative)
        or not _has_internal_fingerprint(
            source_manifest,
            _SOURCE_MANIFEST_FINGERPRINT_FIELD,
        )
        or not _has_internal_fingerprint(
            result_artifact,
            _GATE_RESULT_FINGERPRINT_FIELD,
        )
    ):
        return None

    dependency_manifest_relative = methodology_gate_dependency_manifest_path(
        result_artifact_relative
    )
    if not _is_safe_production_dependency_path(dependency_manifest_relative):
        return None
    dependency_manifest_path = _resolve_repo_regular_file(
        repository_root,
        dependency_manifest_relative,
    )
    if dependency_manifest_path is None:
        return None
    try:
        source_manifest_bytes = source_manifest_path.read_bytes()
        result_artifact_bytes = result_artifact_path.read_bytes()
        manifest_bytes = dependency_manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    source_manifest_sha256 = _sha256_bytes(source_manifest_bytes)
    result_artifact_sha256 = _sha256_bytes(result_artifact_bytes)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != _GATE_DEPENDENCY_MANIFEST_KEYS
        or manifest.get("artifact_id") != _GATE_DEPENDENCY_MANIFEST_ARTIFACT_ID
        or manifest.get("gate_id") != gate_id
        or manifest.get("execution_fingerprint") != execution_fingerprint
        or manifest.get("source_manifest_path") != source_manifest_relative.as_posix()
        or manifest.get("source_manifest_sha256") != source_manifest_sha256
        or manifest.get("result_artifact_path") != result_artifact_relative.as_posix()
        or manifest.get("result_artifact_sha256") != result_artifact_sha256
        or not _has_internal_fingerprint(
            manifest,
            _GATE_DEPENDENCY_MANIFEST_FINGERPRINT_FIELD,
        )
        or _contains_disallowed_evidence_state(manifest)
    ):
        return None

    entries = manifest.get("dependencies")
    if not isinstance(entries, list) or not entries:
        return None
    entry_sort_keys: list[tuple[str, str]] = []
    entry_paths: set[str] = set()
    dependencies: list[MethodologyGateDependency] = []
    structured_artifacts: list[tuple[dict[str, Any], tuple[str, ...]]] = []
    allowed_roles = _allowed_dependency_roles(gate_id)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _GATE_DEPENDENCY_ENTRY_KEYS:
            return None
        role = entry.get("role")
        path_value = entry.get("path")
        byte_sha256 = entry.get("byte_sha256")
        if (
            not isinstance(role, str)
            or not role
            or role not in allowed_roles
            or not isinstance(path_value, str)
            or not path_value
            or not _is_sha256(byte_sha256)
        ):
            return None
        relative_path = Path(path_value)
        if (
            not _is_safe_production_dependency_path(relative_path)
            or path_value in entry_paths
            or relative_path
            in {
                source_manifest_relative,
                result_artifact_relative,
                dependency_manifest_relative,
            }
        ):
            return None
        dependency_path = _resolve_repo_regular_file(repository_root, relative_path)
        if dependency_path is None:
            return None
        try:
            dependency_bytes = dependency_path.read_bytes()
        except OSError:
            return None
        if _sha256_bytes(dependency_bytes) != byte_sha256:
            return None

        artifact_id = entry.get("artifact_id")
        internal_field = entry.get("internal_fingerprint_field")
        internal_fingerprint = entry.get("internal_fingerprint")
        payload: dict[str, Any] | None = None
        if role in _OPAQUE_DEPENDENCY_ROLES:
            if (
                artifact_id is not None
                or internal_field is not None
                or internal_fingerprint is not None
            ):
                return None
        else:
            expected_artifact_id = {
                **_COMMON_DEPENDENCY_ARTIFACT_IDS,
                **_GATE_DEPENDENCY_ARTIFACT_IDS,
            }.get(role)
            expected_internal_field = (
                "bundle_fingerprint"
                if role == _EXECUTION_BINDING_DEPENDENCY_ROLE
                else _GATE_DEPENDENCY_INTERNAL_FINGERPRINT_FIELD
            )
            if (
                not isinstance(artifact_id, str)
                or artifact_id != expected_artifact_id
                or internal_field != expected_internal_field
                or not _is_sha256(internal_fingerprint)
            ):
                return None
            try:
                artifact = json.loads(dependency_bytes)
            except (UnicodeError, json.JSONDecodeError):
                return None
            if not isinstance(artifact, dict) or artifact.get("artifact_id") != artifact_id:
                return None
            if role == _EXECUTION_BINDING_DEPENDENCY_ROLE:
                artifact_binding_valid = _validate_execution_binding_bundle(
                    artifact,
                    authority_execution_fingerprint=execution_fingerprint,
                    source_manifest=source_manifest,
                )
            elif role in _COMMON_DEPENDENCY_ARTIFACT_IDS:
                artifact_binding_valid = set(artifact) == _SOURCE_ROOT_DEPENDENCY_ARTIFACT_KEYS
            else:
                artifact_binding_valid = (
                    set(artifact) == _GATE_DEPENDENCY_ARTIFACT_KEYS
                    and artifact.get("gate_id") == gate_id
                    and artifact.get("execution_fingerprint") == execution_fingerprint
                    and artifact.get("source_manifest_sha256") == source_manifest_sha256
                    and artifact.get("status") == "passed"
                    and artifact.get("evidence_classification") == "production"
                )
            if (
                not artifact_binding_valid
                or artifact.get(internal_field) != internal_fingerprint
                or not _has_internal_fingerprint(artifact, internal_field)
                or (
                    role != _EXECUTION_BINDING_DEPENDENCY_ROLE
                    and _contains_disallowed_evidence_state(artifact)
                )
            ):
                return None
            if role != _EXECUTION_BINDING_DEPENDENCY_ROLE:
                dependency_paths = artifact.get("dependency_paths")
                payload = artifact.get("payload")
                if (
                    not isinstance(dependency_paths, list)
                    or any(
                        not isinstance(item, str)
                        or not item
                        or not _is_safe_production_dependency_path(Path(item))
                        for item in dependency_paths
                    )
                    or dependency_paths != sorted(set(dependency_paths))
                    or not isinstance(payload, dict)
                ):
                    return None
                structured_artifacts.append((artifact, tuple(dependency_paths)))

        entry_sort_keys.append((role, path_value))
        entry_paths.add(path_value)
        dependencies.append(
            MethodologyGateDependency(
                role=role,
                relative_path=relative_path,
                byte_sha256=byte_sha256,
                artifact_id=artifact_id,
                payload=payload,
            )
        )
    if entry_sort_keys != sorted(entry_sort_keys):
        return None

    allowed_references = {
        source_manifest_relative.as_posix(),
        result_artifact_relative.as_posix(),
        *entry_paths,
    }
    for artifact, declared_paths in structured_artifacts:
        if any(path not in entry_paths for path in declared_paths):
            return None
        referenced_paths = _payload_path_references(artifact.get("payload"))
        if referenced_paths is None or not referenced_paths.issubset(set(declared_paths)):
            return None
        if not set(declared_paths).issubset(allowed_references):
            return None

    validated = MethodologyGateDependencyManifest(
        relative_path=dependency_manifest_relative,
        manifest_fingerprint=manifest[_GATE_DEPENDENCY_MANIFEST_FINGERPRINT_FIELD],
        dependencies=tuple(dependencies),
    )
    return (
        validated
        if _validate_common_methodology_dependencies(
            validated,
            source_manifest=source_manifest,
        )
        else None
    )


def _validate_common_methodology_dependencies(
    manifest: MethodologyGateDependencyManifest,
    *,
    source_manifest: dict[str, Any],
) -> bool:
    source_items = manifest.by_role("source_item")
    model_artifacts = manifest.by_role("model_artifact")
    package_locks = manifest.by_role("package_lock")
    source_inventories = manifest.by_role("source_inventory_manifest")
    case_manifests = manifest.by_role("case_manifest")
    configuration_manifests = manifest.by_role("configuration_manifest")
    execution_binding_bundles = manifest.by_role(_EXECUTION_BINDING_DEPENDENCY_ROLE)
    if not (
        len(source_items) == source_manifest.get("source_count")
        and len(model_artifacts) == len(source_manifest.get("model_artifact_hashes", []))
        and len(package_locks) == 1
        and len(source_inventories) == 1
        and len(case_manifests) == 1
        and len(configuration_manifests) == 1
        and len(execution_binding_bundles) == 1
    ):
        return False
    if (
        {item.byte_sha256 for item in source_items} != set(source_manifest.get("source_hashes", []))
        or {item.byte_sha256 for item in model_artifacts}
        != set(source_manifest.get("model_artifact_hashes", []))
        or package_locks[0].byte_sha256 != source_manifest.get("package_lock_sha256")
        or case_manifests[0].byte_sha256 != source_manifest.get("case_manifest_sha256")
        or configuration_manifests[0].byte_sha256
        != source_manifest.get("configuration_manifest_sha256")
    ):
        return False

    inventory_payload = source_inventories[0].payload
    case_payload = case_manifests[0].payload
    configuration_payload = configuration_manifests[0].payload
    if (
        inventory_payload is None
        or set(inventory_payload)
        != {
            "source_count",
            "source_item_count",
            "source_hashes",
            "source_paths",
        }
        or inventory_payload.get("source_count") != source_manifest.get("source_count")
        or inventory_payload.get("source_item_count") != source_manifest.get("source_item_count")
        or inventory_payload.get("source_hashes")
        != sorted(source_manifest.get("source_hashes", []))
        or inventory_payload.get("source_paths")
        != sorted(item.relative_path.as_posix() for item in source_items)
        or case_payload is None
        or set(case_payload) != {"case_count", "case_scope"}
        or not _is_positive_int(case_payload.get("case_count"))
        or case_payload.get("case_scope") not in _PRODUCTION_CASE_SCOPES
        or configuration_payload is None
        or set(configuration_payload)
        != {
            "evaluation_policy_id",
            "method_id",
            "tokenizer_id",
        }
        or configuration_payload.get("evaluation_policy_id")
        != _FROZEN_TARGET_PIPELINE["evaluation_policy_id"]
        or configuration_payload.get("method_id") != _FROZEN_TARGET_PIPELINE["method_id"]
        or configuration_payload.get("tokenizer_id") != _FROZEN_TARGET_PIPELINE["tokenizer_id"]
    ):
        return False
    return True


def _allowed_dependency_roles(gate_id: str) -> set[str]:
    common_roles = {
        "case_manifest",
        "configuration_manifest",
        _EXECUTION_BINDING_DEPENDENCY_ROLE,
        "model_artifact",
        "package_lock",
        "source_inventory_manifest",
        "source_item",
    }
    gate_roles = {
        "source_completeness_compared_with_raw_oracle": {
            "observation_reconciliation_report",
            "raw_source_oracle_manifest",
        },
        "evaluation_reports_bind_execution_fingerprint": {
            "evaluation_report",
            "evaluation_report_index",
        },
        "same_pipeline_real_source_ablation": {"ablation_arm_result"},
        "real_user_end_answer_acceptance": {
            "final_answer_acceptance_report",
        },
    }
    return common_roles | gate_roles.get(gate_id, set())


def _repo_relative_path(repository_root: Path, path: Path) -> Path | None:
    try:
        resolved_root = repository_root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        return resolved_path.relative_to(resolved_root)
    except (OSError, ValueError):
        return None


def _is_safe_production_dependency_path(relative_path: Path) -> bool:
    if relative_path.is_absolute() or not relative_path.parts or ".." in relative_path.parts:
        return False
    for part in relative_path.parts:
        lowered = part.lower()
        tokens = {token for token in re.split(r"[^a-z0-9]+", lowered) if token}
        if lowered in _DISALLOWED_EVIDENCE_PATH_TOKENS:
            return False
        if tokens.intersection(_DISALLOWED_EVIDENCE_PATH_TOKENS - {".test-tmp"}):
            return False
    return True


def _contains_disallowed_evidence_state(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = key.lower()
            if (
                normalized_key
                in {
                    "allow_blocked",
                    "diagnostic_only",
                    "diagnostic_subset_only",
                    "preflight_only",
                }
                and item is True
            ):
                return True
            if (
                (
                    normalized_key == "status"
                    or normalized_key.endswith("_status")
                    or normalized_key.endswith("_classification")
                    or normalized_key.endswith("_mode")
                    or normalized_key.endswith("_phase")
                )
                and isinstance(item, str)
                and item.lower() in _DISALLOWED_EVIDENCE_STATES
            ):
                return True
            if _contains_disallowed_evidence_state(item):
                return True
        return False
    if isinstance(value, list):
        return any(_contains_disallowed_evidence_state(item) for item in value)
    return False


def _payload_path_references(value: Any) -> set[str] | None:
    references: set[str] = set()
    if not isinstance(value, dict):
        return references
    for key, item in value.items():
        if key.endswith("_path"):
            path_values = [item]
        elif key.endswith("_paths"):
            if not isinstance(item, list):
                return None
            path_values = item
        else:
            nested = _payload_path_references(item)
            if nested is None:
                return None
            references.update(nested)
            continue
        for path_value in path_values:
            if (
                not isinstance(path_value, str)
                or not path_value
                or not _is_safe_production_dependency_path(Path(path_value))
            ):
                return None
            references.add(path_value)
    return references


def _has_internal_fingerprint(value: dict[str, Any], field_name: str) -> bool:
    fingerprint = value.get(field_name)
    if not _is_sha256(fingerprint):
        return False
    fingerprint_payload = dict(value)
    del fingerprint_payload[field_name]
    return fingerprint == _canonical_sha256(fingerprint_payload)


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _is_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def _validate_execution_binding_bundle(
    value: dict[str, Any],
    *,
    authority_execution_fingerprint: str,
    source_manifest: dict[str, Any],
) -> bool:
    if (
        set(value) != _EXECUTION_BINDING_BUNDLE_KEYS
        or value.get("artifact_id") != _EXECUTION_BINDING_BUNDLE_ARTIFACT_ID
        or value.get("schema_version") != _EXECUTION_BINDING_SCHEMA_VERSION
        or value.get("status") not in {"blocked", "passed"}
        or value.get("execution_binding_status") != "passed"
    ):
        return False
    if any(
        not _is_sha256(value.get(field_name))
        for field_name in (
            "run_binding_fingerprint",
            "source_binding_fingerprint",
            "execution_fingerprint",
            "blocking_status_fingerprint",
            "bundle_fingerprint",
        )
    ):
        return False

    component_fingerprints = value.get("component_artifact_fingerprints")
    bound_fingerprints = value.get("bound_fingerprints")
    execution_binding = value.get("execution_binding")
    if (
        not isinstance(component_fingerprints, dict)
        or set(component_fingerprints) != _EXECUTION_BINDING_COMPONENT_KEYS
        or any(not _is_sha256(item) for item in component_fingerprints.values())
        or not isinstance(bound_fingerprints, dict)
        or not bound_fingerprints
        or any(not _is_sha256(item) for item in bound_fingerprints.values())
        or not isinstance(execution_binding, dict)
        or set(execution_binding) != _EXECUTION_BINDING_KEYS
        or execution_binding.get("artifact_id") != _EXECUTION_BINDING_ARTIFACT_ID
        or execution_binding.get("schema_version") != _EXECUTION_BINDING_SCHEMA_VERSION
        or execution_binding.get("source_binding_fingerprint")
        != value["source_binding_fingerprint"]
        or not _is_sha256(execution_binding.get("source_completeness_report_sha256"))
        or not _is_sha256(execution_binding.get("source_completeness_report_fingerprint"))
    ):
        return False

    execution_bound_fingerprints = execution_binding.get("bound_fingerprints")
    if (
        not isinstance(execution_bound_fingerprints, dict)
        or set(execution_bound_fingerprints) != _EXECUTION_IDENTITY_BOUND_FINGERPRINT_KEYS
        or any(not _is_sha256(item) for item in execution_bound_fingerprints.values())
        or any(
            bound_fingerprints.get(key) != fingerprint
            for key, fingerprint in execution_bound_fingerprints.items()
        )
        or execution_bound_fingerprints.get("authority_execution")
        != authority_execution_fingerprint
        or value["execution_fingerprint"] != _canonical_sha256(execution_binding)
    ):
        return False

    counts = value.get("counts")
    statuses = value.get("statuses")
    blocker_ids = value.get("blocking_status_ids")
    if (
        not isinstance(counts, dict)
        or not counts
        or any(not _is_nonnegative_int(item) for item in counts.values())
        or counts.get("source_item_count") != source_manifest.get("source_item_count")
        or counts.get("observation_count") != counts.get("source_item_count")
        or counts.get("unexplained_loss_count") != 0
        or not isinstance(statuses, dict)
        or not statuses
        or any(
            item not in {"blocked", "failed", "missing", "passed", "ready"}
            for item in statuses.values()
        )
        or not isinstance(blocker_ids, list)
        or any(not isinstance(item, str) or not item for item in blocker_ids)
        or blocker_ids != sorted(set(blocker_ids))
        or value["blocking_status_fingerprint"] != _canonical_sha256(blocker_ids)
        or (value["status"] == "passed") != (not blocker_ids)
        or not _has_internal_fingerprint(value, "bundle_fingerprint")
    ):
        return False
    return True


def _gate_execution_binding_reference_matches(
    *,
    repository_root: Path,
    reference: Any,
    dependency_manifest: dict[str, Any],
) -> bool:
    if (
        not isinstance(reference, dict)
        or set(reference) != _GATE_EXECUTION_BINDING_REFERENCE_KEYS
        or reference.get("role") != _EXECUTION_BINDING_DEPENDENCY_ROLE
        or not _is_sha256(reference.get("byte_sha256"))
        or not _is_sha256(reference.get("bundle_fingerprint"))
        or not _is_sha256(reference.get("complete_execution_fingerprint"))
    ):
        return False
    path_value = reference.get("path")
    if (
        not isinstance(path_value, str)
        or not path_value
        or not _is_safe_production_dependency_path(Path(path_value))
    ):
        return False
    matching_entries = [
        entry
        for entry in dependency_manifest.get("dependencies", [])
        if isinstance(entry, dict) and entry.get("role") == _EXECUTION_BINDING_DEPENDENCY_ROLE
    ]
    if len(matching_entries) != 1:
        return False
    entry = matching_entries[0]
    if (
        set(entry) != _GATE_DEPENDENCY_ENTRY_KEYS
        or entry.get("path") != path_value
        or entry.get("artifact_id") != _EXECUTION_BINDING_BUNDLE_ARTIFACT_ID
        or entry.get("byte_sha256") != reference["byte_sha256"]
        or entry.get("internal_fingerprint_field") != "bundle_fingerprint"
        or entry.get("internal_fingerprint") != reference["bundle_fingerprint"]
    ):
        return False
    bundle_path = _resolve_repo_regular_file(repository_root, Path(path_value))
    if bundle_path is None:
        return False
    try:
        bundle_bytes = bundle_path.read_bytes()
        bundle = json.loads(bundle_bytes)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        _sha256_bytes(bundle_bytes) == reference["byte_sha256"]
        and isinstance(bundle, dict)
        and bundle.get("artifact_id") == _EXECUTION_BINDING_BUNDLE_ARTIFACT_ID
        and bundle.get("bundle_fingerprint") == reference["bundle_fingerprint"]
        and bundle.get("execution_fingerprint") == reference["complete_execution_fingerprint"]
    )


def _production_source_completeness_validator(
    **kwargs: Any,
) -> bool:
    manifest = _load_methodology_gate_dependency_manifest(
        gate_id="source_completeness_compared_with_raw_oracle",
        **kwargs,
    )
    if manifest is None:
        return False
    result_artifact = kwargs["result_artifact"]
    inventories = manifest.by_role("source_inventory_manifest")
    raw_oracles = manifest.by_role("raw_source_oracle_manifest")
    reconciliations = manifest.by_role("observation_reconciliation_report")
    if not (len(inventories) == len(raw_oracles) == len(reconciliations) == 1):
        return False
    inventory = inventories[0]
    raw_oracle = raw_oracles[0]
    reconciliation = reconciliations[0]
    raw_payload = raw_oracle.payload
    reconciliation_payload = reconciliation.payload
    if (
        raw_payload is None
        or set(raw_payload)
        != {
            "raw_source_unit_count",
            "source_inventory_sha256",
        }
        or raw_payload.get("raw_source_unit_count") != result_artifact.get("raw_source_unit_count")
        or raw_payload.get("source_inventory_sha256") != inventory.byte_sha256
        or reconciliation_payload is None
        or set(reconciliation_payload)
        != {
            "emitted_observation_unit_count",
            "loss_taxonomy_counts",
            "policy_redacted_unit_count",
            "raw_source_oracle_sha256",
            "raw_source_unit_count",
            "source_inventory_sha256",
            "unexplained_loss_unit_count",
        }
        or reconciliation_payload.get("raw_source_oracle_sha256") != raw_oracle.byte_sha256
        or reconciliation_payload.get("source_inventory_sha256") != inventory.byte_sha256
    ):
        return False
    return all(
        reconciliation_payload.get(field_name) == result_artifact.get(field_name)
        for field_name in (
            "raw_source_unit_count",
            "emitted_observation_unit_count",
            "policy_redacted_unit_count",
            "unexplained_loss_unit_count",
            "loss_taxonomy_counts",
        )
    )


def _production_execution_report_binding_validator(
    **kwargs: Any,
) -> bool:
    manifest = _load_methodology_gate_dependency_manifest(
        gate_id="evaluation_reports_bind_execution_fingerprint",
        **kwargs,
    )
    if manifest is None:
        return False
    source_manifest = kwargs["source_manifest"]
    result_artifact = kwargs["result_artifact"]
    indexes = manifest.by_role("evaluation_report_index")
    reports = manifest.by_role("evaluation_report")
    if len(indexes) != 1 or not reports:
        return False
    report_paths = sorted(item.relative_path.as_posix() for item in reports)
    report_hashes = sorted(item.byte_sha256 for item in reports)
    index_payload = indexes[0].payload
    if (
        index_payload is None
        or set(index_payload) != {"report_count", "report_hashes", "report_paths"}
        or index_payload.get("report_count") != len(reports)
        or index_payload.get("report_paths") != report_paths
        or index_payload.get("report_hashes") != report_hashes
        or result_artifact.get("report_count") != len(reports)
        or sorted(result_artifact.get("report_hashes", [])) != report_hashes
    ):
        return False
    for report in reports:
        payload = report.payload
        if (
            payload is None
            or set(payload)
            != {
                "case_manifest_sha256",
                "evaluation_policy_fingerprint",
                "execution_status",
                "quality_gate_status",
                "report_kind",
            }
            or payload.get("case_manifest_sha256") != source_manifest.get("case_manifest_sha256")
            or payload.get("evaluation_policy_fingerprint")
            != source_manifest.get("configuration_manifest_sha256")
            or payload.get("execution_status") != "passed"
            or payload.get("quality_gate_status") != "passed"
            or payload.get("report_kind") != "completed_quality_report"
        ):
            return False
    return True


def _production_same_pipeline_real_source_ablation_validator(
    **kwargs: Any,
) -> bool:
    manifest = _load_methodology_gate_dependency_manifest(
        gate_id="same_pipeline_real_source_ablation",
        **kwargs,
    )
    if manifest is None:
        return False
    source_manifest = kwargs["source_manifest"]
    result_artifact = kwargs["result_artifact"]
    arm_results = manifest.by_role("ablation_arm_result")
    if len(arm_results) != len(_ABLATION_ARM_IDS):
        return False
    by_arm: dict[str, MethodologyGateDependency] = {}
    for dependency in arm_results:
        payload = dependency.payload
        if (
            payload is None
            or set(payload)
            != {
                "adjudicated_case_count",
                "arm_id",
                "case_count",
                "case_manifest_sha256",
                "completed_case_count",
                "evaluation_policy_fingerprint",
                "execution_status",
                "quality_gate_status",
            }
            or payload.get("arm_id") not in _ABLATION_ARM_IDS
            or payload.get("arm_id") in by_arm
            or payload.get("case_count") != result_artifact.get("case_count")
            or payload.get("completed_case_count") != result_artifact.get("completed_case_count")
            or payload.get("adjudicated_case_count")
            != result_artifact.get("adjudicated_case_count")
            or payload.get("case_manifest_sha256") != source_manifest.get("case_manifest_sha256")
            or payload.get("evaluation_policy_fingerprint")
            != source_manifest.get("configuration_manifest_sha256")
            or payload.get("execution_status") != "passed"
            or payload.get("quality_gate_status") != "passed"
        ):
            return False
        by_arm[payload["arm_id"]] = dependency
    return set(by_arm) == _ABLATION_ARM_IDS and result_artifact.get("result_hashes_by_arm") == {
        arm_id: by_arm[arm_id].byte_sha256 for arm_id in sorted(by_arm)
    }


def _production_real_user_end_answer_acceptance_validator(
    **kwargs: Any,
) -> bool:
    manifest = _load_methodology_gate_dependency_manifest(
        gate_id="real_user_end_answer_acceptance",
        **kwargs,
    )
    if manifest is None:
        return False
    source_manifest = kwargs["source_manifest"]
    result_artifact = kwargs["result_artifact"]
    case_manifests = manifest.by_role("case_manifest")
    reports = manifest.by_role("final_answer_acceptance_report")
    if (
        len(case_manifests) != 1
        or case_manifests[0].payload is None
        or case_manifests[0].payload.get("case_scope") != "combined_independent_acceptance"
        or len(reports) != 1
        or reports[0].payload is None
    ):
        return False
    report_payload = reports[0].payload
    expected_report_keys = {
        "acceptance_profile_id",
        "acceptance_scope",
        "adjudicated_case_count",
        "answerable_case_count",
        "case_count",
        "case_manifest_sha256",
        "citation_supported_correct_count",
        "correct_answer_count",
        "evaluation_policy_fingerprint",
        "execution_status",
        "observed_accuracy_ppm",
        "observed_citation_support_ppm",
        "permission_denial_case_count",
        "permission_denial_pass_count",
        "quality_gate_status",
    }
    if (
        set(report_payload) != expected_report_keys
        or report_payload.get("acceptance_scope") != "independent_holdout_and_transfer"
        or report_payload.get("case_manifest_sha256") != source_manifest.get("case_manifest_sha256")
        or report_payload.get("evaluation_policy_fingerprint")
        != source_manifest.get("configuration_manifest_sha256")
        or report_payload.get("execution_status") != "passed"
        or report_payload.get("quality_gate_status") != "passed"
    ):
        return False
    return all(
        report_payload.get(field_name) == result_artifact.get(field_name)
        for field_name in _GATE_RESULT_KEYS["real_user_end_answer_acceptance"] - _RESULT_COMMON_KEYS
    )


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
            evidence_relative_path = Path(value)
            if not _is_safe_production_dependency_path(evidence_relative_path):
                continue
            path = _resolve_repo_regular_file(repository_root, evidence_relative_path)
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
                and payload.get("schema_version") == _GATE_EVIDENCE_SCHEMA_VERSION
                and payload.get("authority_id") == authority_id
                and payload.get("gate_id") == gate_id
                and payload.get("execution_fingerprint") == execution_fingerprint
                and payload.get("validator_id") == _GATE_VALIDATOR_IDS[gate_id]
                and payload.get("status") == "passed"
                and payload.get("evidence_classification") == "production"
                and payload.get("promotion_status") == "not_performed"
                and _has_internal_fingerprint(
                    payload,
                    _GATE_EVIDENCE_FINGERPRINT_FIELD,
                )
            ):
                continue

            source_manifest_value = payload.get("source_manifest_path")
            result_artifact_value = payload.get("result_artifact_path")
            dependency_manifest_value = payload.get("dependency_manifest_path")
            if not isinstance(source_manifest_value, str) or not source_manifest_value:
                continue
            if not isinstance(result_artifact_value, str) or not result_artifact_value:
                continue
            if not isinstance(dependency_manifest_value, str) or not dependency_manifest_value:
                continue
            source_manifest_relative = Path(source_manifest_value)
            result_artifact_relative = Path(result_artifact_value)
            dependency_manifest_relative = Path(dependency_manifest_value)
            expected_dependency_manifest_relative = methodology_gate_dependency_manifest_path(
                result_artifact_relative
            )
            if (
                not _is_safe_production_dependency_path(source_manifest_relative)
                or not _is_safe_production_dependency_path(result_artifact_relative)
                or not _is_safe_production_dependency_path(dependency_manifest_relative)
                or dependency_manifest_relative != expected_dependency_manifest_relative
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
            dependency_manifest_path = _resolve_repo_regular_file(
                repository_root,
                dependency_manifest_relative,
            )
            if (
                source_manifest_path is None
                or result_artifact_path is None
                or dependency_manifest_path is None
            ):
                continue
            try:
                source_manifest_bytes = source_manifest_path.read_bytes()
                result_artifact_bytes = result_artifact_path.read_bytes()
                dependency_manifest_bytes = dependency_manifest_path.read_bytes()
                dependency_manifest = json.loads(dependency_manifest_bytes)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            source_manifest_sha256 = f"sha256:{hashlib.sha256(source_manifest_bytes).hexdigest()}"
            result_artifact_sha256 = f"sha256:{hashlib.sha256(result_artifact_bytes).hexdigest()}"
            dependency_manifest_sha256 = _sha256_bytes(dependency_manifest_bytes)
            dependency_count = payload.get("dependency_count")
            if not (
                is_sha256(payload.get("source_manifest_sha256"))
                and payload.get("source_manifest_sha256") == source_manifest_sha256
                and is_sha256(payload.get("result_artifact_sha256"))
                and payload.get("result_artifact_sha256") == result_artifact_sha256
                and is_sha256(payload.get("dependency_manifest_sha256"))
                and payload.get("dependency_manifest_sha256") == dependency_manifest_sha256
                and isinstance(dependency_manifest, dict)
                and set(dependency_manifest) == _GATE_DEPENDENCY_MANIFEST_KEYS
                and dependency_manifest.get("artifact_id") == _GATE_DEPENDENCY_MANIFEST_ARTIFACT_ID
                and dependency_manifest.get("gate_id") == gate_id
                and dependency_manifest.get("execution_fingerprint") == execution_fingerprint
                and dependency_manifest.get("source_manifest_path") == source_manifest_value
                and dependency_manifest.get("source_manifest_sha256") == source_manifest_sha256
                and dependency_manifest.get("result_artifact_path") == result_artifact_value
                and dependency_manifest.get("result_artifact_sha256") == result_artifact_sha256
                and _has_internal_fingerprint(
                    dependency_manifest,
                    _GATE_DEPENDENCY_MANIFEST_FINGERPRINT_FIELD,
                )
                and payload.get("dependency_manifest_fingerprint")
                == dependency_manifest.get(_GATE_DEPENDENCY_MANIFEST_FINGERPRINT_FIELD)
                and is_positive_int(dependency_count)
                and isinstance(dependency_manifest.get("dependencies"), list)
                and dependency_count == len(dependency_manifest["dependencies"])
            ):
                continue
            if not _gate_execution_binding_reference_matches(
                repository_root=repository_root,
                reference=payload.get("execution_binding"),
                dependency_manifest=dependency_manifest,
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
                or not _has_internal_fingerprint(
                    source_manifest,
                    _SOURCE_MANIFEST_FINGERPRINT_FIELD,
                )
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
                or not _has_internal_fingerprint(
                    result_artifact,
                    _GATE_RESULT_FINGERPRINT_FIELD,
                )
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
    expected_helper: str | None,
    expected_callers: set[str],
) -> bool:
    if not isinstance(tree, ast.Module) or expected_helper is None:
        return False
    canonical_import_count = 0
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            bound_name = alias.asname or alias.name
            if bound_name != expected_helper:
                continue
            if (
                node.module == "formowl_core"
                and alias.name == expected_helper
                and alias.asname is None
            ):
                canonical_import_count += 1
            else:
                return False
    if canonical_import_count != 1:
        return False
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
    return all(
        any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_tokenize"
            for node in ast.walk(caller)
        )
        for caller in callers.values()
    )


def _literal_module_assignment(tree: ast.Module, name: str) -> Any:
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and (
            any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
            if isinstance(node, ast.Assign)
            else isinstance(node.target, ast.Name) and node.target.id == name
        )
    ]
    if len(matches) != 1:
        return None
    value = matches[0].value
    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError):
        return None


def _top_level_function(
    tree: ast.Module,
    name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    ]
    return matches[0] if len(matches) == 1 else None


def _class_method(
    tree: ast.Module,
    class_name: str,
    method_name: str,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    classes = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(classes) != 1:
        return None
    matches = [
        node
        for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    ]
    return matches[0] if len(matches) == 1 else None


def _called_function_names(
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> set[str]:
    if function is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _function_default_is_true(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter_name: str,
) -> bool:
    return _function_default_literal(function, parameter_name) is True


def _function_default_is_false(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter_name: str,
) -> bool:
    return _function_default_literal(function, parameter_name) is False


def _function_default_literal(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    parameter_name: str,
) -> Any:
    positional = [*function.args.posonlyargs, *function.args.args]
    positional_defaults = [None] * (len(positional) - len(function.args.defaults)) + list(
        function.args.defaults
    )
    for argument, default in zip(positional, positional_defaults):
        if argument.arg == parameter_name and default is not None:
            try:
                return ast.literal_eval(default)
            except (ValueError, TypeError):
                return None
    for argument, default in zip(function.args.kwonlyargs, function.args.kw_defaults):
        if argument.arg == parameter_name and default is not None:
            try:
                return ast.literal_eval(default)
            except (ValueError, TypeError):
                return None
    return None


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _invalid_runtime_pipeline_probe() -> RuntimePipelineProbe:
    return RuntimePipelineProbe(
        method_id=None,
        method_fingerprint=None,
        runtime_probe_valid=False,
        normal_entrypoint_bound=False,
        typed_plan_bound=False,
        strong_rag_bound=False,
        entity_graph_bound=False,
        soft_ontology_bound=False,
        exact_executor_bound=False,
        cited_answer_bound=False,
        legacy_or_ascii_fallback_absent=False,
    )


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
        runtime_pipeline_probe=_invalid_runtime_pipeline_probe(),
        errors=(error,),
    )


_GATE_EXECUTABLE_VALIDATORS.update(
    {
        "source_completeness_compared_with_raw_oracle": (_production_source_completeness_validator),
        "evaluation_reports_bind_execution_fingerprint": (
            _production_execution_report_binding_validator
        ),
        "same_pipeline_real_source_ablation": (
            _production_same_pipeline_real_source_ablation_validator
        ),
        "real_user_end_answer_acceptance": (_production_real_user_end_answer_acceptance_validator),
    }
)


__all__ = [
    "AUTHORITY_RELATIVE_PATH",
    "MethodologyAuthorityResult",
    "MethodologyGateDependency",
    "MethodologyGateDependencyManifest",
    "RuntimePipelineProbe",
    "TokenizerProbe",
    "check_methodology_authority",
    "methodology_gate_dependency_manifest_path",
    "probe_runtime_pipeline",
    "probe_runtime_tokenizers",
    "validate_methodology_gate_dependency_manifest",
]
