#!/usr/bin/env python3
"""Build a fail-closed Issue #56 execution-fingerprint acceptance bundle.

The command accepts only safe component attestations. It binds their
fingerprints to the current code tree, canonical image attestation, frozen
runtime profiles, and executable methodology-authority state. It never reads
private source manifests and never emits source payloads or local paths.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
for import_root in (ROOT, PYTHON_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from formowl_contract import assert_no_public_raw_references, sha256_json  # noqa: E402
from formowl_core import (  # noqa: E402
    build_issue56_execution_component_binding,
    issue56_target_dense_embedding_profile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_core.methodology_authority import check_methodology_authority  # noqa: E402
from formowl_mail.answer import (  # noqa: E402
    EvidenceAnswerBudget,
    ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID,
    ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT,
)
from formowl_mail.hybrid import (  # noqa: E402
    ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
    ISSUE56_TARGET_RUNTIME_METHOD_ID,
)
from formowl_mail.candidates import (  # noqa: E402
    SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT,
    TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
)
from scripts.issue56_operational_budget import (  # noqa: E402
    FROZEN_CANONICAL_IMAGE_ID,
    FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT,
    FROZEN_CANONICAL_IMAGE_REFERENCE,
)
from scripts.issue56_source_identifier_candidates import (  # noqa: E402
    CANDIDATE_ARTIFACT_SCHEMA_VERSION as SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
    IDENTITY_SCOPE_POLICY_FINGERPRINT,
    PRIVATE_ARTIFACT_ID as SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
    RESOLUTION_POLICY_FINGERPRINT as SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT,
)

INPUT_ARTIFACT_ID = "formowl_issue56_execution_fingerprint_inputs_v1"
BUNDLE_ARTIFACT_ID = "formowl_issue56_execution_fingerprint_acceptance_bundle_v1"
REPORT_ARTIFACT_ID = "formowl_issue56_execution_fingerprint_public_report_v1"
ERROR_ARTIFACT_ID = "formowl_issue56_execution_fingerprint_rejection_v1"
UAT_ARTIFACT_ID = "formowl_issue56_simulated_human_uat_v1"
UAT_DEVELOPMENT_BOUNDARY_ID = "diagnostic_same_pipeline_not_independent_holdout"
SCHEMA_VERSION = 1
CANONICAL_IMAGE_REFERENCE = FROZEN_CANONICAL_IMAGE_REFERENCE
IMAGE_ATTESTOR_ID = "local_docker_image_inspect_v1"
CASE_COUNT = 100
EVALUATOR_ID = "issue56_simulated_human_adjudication_v1"
GRAPH_ADAPTER_ID = "source_backed_mail_candidate_graph_v2"
SOURCE_GRAPH_POLICY_ID = "source_backed_mail_candidate_graph_v2"
SOURCE_IDENTIFIER_ADAPTER_ID = "source_bound_identifier_mentions_graph_adapter_v3"
GRAPH_RELATION_TYPES = ("co_occurs_with", "mentions_identifier")
ONTOLOGY_TARGET = "Artifact"

SOURCE_COMPONENT_ID = "formowl_issue56_source_acceptance_component_v1"
LEXICAL_INDEX_COMPONENT_ID = "formowl_issue56_lexical_index_acceptance_component_v1"
GRAPH_ONTOLOGY_COMPONENT_ID = "formowl_issue56_graph_ontology_acceptance_component_v1"
ANSWER_COMPONENT_ID = "formowl_issue56_answer_acceptance_component_v1"
EVALUATION_COMPONENT_ID = "formowl_issue56_evaluation_acceptance_component_v1"
CODE_COMPONENT_ID = "formowl_issue56_code_acceptance_component_v1"
IMAGE_COMPONENT_ID = "formowl_issue56_image_acceptance_component_v1"
AUTHORITY_COMPONENT_ID = "formowl_issue56_authority_acceptance_component_v1"

REQUIRED_COMPONENT_NAMES = (
    "source_component",
    "lexical_index_component",
    "graph_ontology_component",
    "answer_component",
    "evaluation_component",
    "code_component",
    "image_component",
    "authority_component",
)

READINESS_BLOCKER_IDS = (
    "source_completeness_not_passed",
    "source_completeness_authority_gate_not_passed",
    "uat_quality_gate_not_passed",
    "operational_budget_not_passed",
    "independent_holdout_not_passed",
    "transfer_evaluation_not_passed",
    "final_answer_acceptance_not_passed",
    "real_source_ablation_authority_gate_not_passed",
)

_HASH_FIELD = "artifact_fingerprint"
_HASH_LENGTH = 71
_MAX_INPUT_BYTES = 2 * 1024 * 1024
_MAX_UAT_REPORT_BYTES = 4 * 1024 * 1024
_ALLOWED_STATUSES = {"passed", "blocked", "failed", "missing"}
_CODE_DIRECTORY_SCOPES = ("python", "scripts", "containers")
_CODE_FILE_SCOPES = ("pyproject.toml", "compose.yaml")

_TOP_LEVEL_KEYS = {
    "artifact_id",
    "schema_version",
    "status",
    "run_binding_fingerprint",
    *REQUIRED_COMPONENT_NAMES,
    _HASH_FIELD,
}
_COMMON_COMPONENT_KEYS = {
    "artifact_id",
    "schema_version",
    "status",
    "run_binding_fingerprint",
    _HASH_FIELD,
}
_COMPONENT_KEYS = {
    "source_component": _COMMON_COMPONENT_KEYS
    | {
        "source_binding_fingerprint",
        "source_snapshot_fingerprint",
        "completeness_report_fingerprint",
        "source_inventory_fingerprint",
        "source_item_count",
        "observation_count",
        "unexplained_loss_count",
    },
    "lexical_index_component": _COMMON_COMPONENT_KEYS
    | {
        "source_binding_fingerprint",
        "lexical_profile_fingerprint",
        "query_profile_fingerprint",
        "evidence_profile_fingerprint",
        "dense_profile_fingerprint",
        "runtime_component_fingerprint",
        "index_fingerprint",
        "index_count",
        "ascii_fallback_count",
    },
    "graph_ontology_component": _COMMON_COMPONENT_KEYS
    | {
        "source_binding_fingerprint",
        "graph_artifact_fingerprint",
        "graph_adapter_fingerprint",
        "source_graph_policy_fingerprint",
        "source_identifier_adapter_fingerprint",
        "relation_type_hash_set_fingerprint",
        "source_identifier_candidate_artifact_fingerprint",
        "source_identifier_candidate_binding_fingerprint",
        "source_identifier_candidate_schema_fingerprint",
        "source_identifier_identity_scope_mode_fingerprint",
        "source_identifier_identity_scope_fingerprint",
        "source_identifier_identity_scope_binding_fingerprint",
        "source_identifier_identity_scope_attestation_byte_fingerprint",
        "source_identifier_identity_scope_attestation_fingerprint",
        "source_identifier_identity_scope_policy_fingerprint",
        "source_identifier_operator_approval_fingerprint",
        "source_identifier_mode_approval_fingerprint",
        "source_identifier_extraction_policy_fingerprint",
        "source_identifier_resolution_policy_fingerprint",
        "source_identifier_identity_scope_graph_binding_set_fingerprint",
        "complete_identifier_mention_batch_fingerprint",
        "selected_identifier_mention_batch_fingerprint",
        "complete_identifier_mention_fingerprint_set_hash",
        "authorized_identifier_mention_fingerprint_set_hash",
        "complete_identifier_resolution_fingerprint",
        "selected_identifier_resolution_fingerprint",
        "identifier_resolution_fingerprint_set_hash",
        "ontology_artifact_fingerprint",
        "ontology_target_fingerprint",
        "graph_node_count",
        "graph_edge_count",
        "unresolved_evidence_hop_count",
        "complete_identifier_mention_count",
        "selected_identifier_mention_count",
        "authorized_identifier_mention_count",
        "complete_resolved_identifier_candidate_count",
        "selected_resolved_identifier_candidate_count",
    },
    "answer_component": _COMMON_COMPONENT_KEYS
    | {
        "source_binding_fingerprint",
        "answer_model_fingerprint",
        "answer_prompt_fingerprint",
        "answer_budget_fingerprint",
        "answer_count",
        "final_answer_acceptance_status",
    },
    "evaluation_component": _COMMON_COMPONENT_KEYS
    | {
        "source_binding_fingerprint",
        "evaluator_fingerprint",
        "quality_gate_report_fingerprint",
        "uat_report_fingerprint",
        "uat_content_fingerprint",
        "uat_run_fingerprint",
        "runtime_method_fingerprint",
        "quality_gate_status",
        "operational_budget_status",
        "independent_holdout_status",
        "transfer_evaluation_status",
        "evaluated_case_count",
    },
    "code_component": _COMMON_COMPONENT_KEYS
    | {
        "commit_fingerprint",
        "code_tree_fingerprint",
        "code_tree_scope_fingerprint",
        "script_fingerprint",
        "code_file_count",
        "changed_entry_count",
    },
    "image_component": _COMMON_COMPONENT_KEYS
    | {
        "image_reference_fingerprint",
        "image_id",
        "image_metadata_fingerprint",
        "attestor_fingerprint",
    },
    "authority_component": _COMMON_COMPONENT_KEYS
    | {
        "methodology_ready_status",
        "authority_state_fingerprint",
        "authority_execution_fingerprint",
        "blocking_gate_set_fingerprint",
        "blocking_gate_count",
        "pipeline_source_binding_count",
        "source_completeness_gate_status",
        "real_source_ablation_gate_status",
    },
}
_COMPONENT_ARTIFACT_IDS = {
    "source_component": SOURCE_COMPONENT_ID,
    "lexical_index_component": LEXICAL_INDEX_COMPONENT_ID,
    "graph_ontology_component": GRAPH_ONTOLOGY_COMPONENT_ID,
    "answer_component": ANSWER_COMPONENT_ID,
    "evaluation_component": EVALUATION_COMPONENT_ID,
    "code_component": CODE_COMPONENT_ID,
    "image_component": IMAGE_COMPONENT_ID,
    "authority_component": AUTHORITY_COMPONENT_ID,
}
_COUNT_FIELDS = {
    "source_component": {
        "source_item_count",
        "observation_count",
        "unexplained_loss_count",
    },
    "lexical_index_component": {"index_count", "ascii_fallback_count"},
    "graph_ontology_component": {
        "graph_node_count",
        "graph_edge_count",
        "unresolved_evidence_hop_count",
        "complete_identifier_mention_count",
        "selected_identifier_mention_count",
        "authorized_identifier_mention_count",
        "complete_resolved_identifier_candidate_count",
        "selected_resolved_identifier_candidate_count",
    },
    "answer_component": {"answer_count"},
    "evaluation_component": {"evaluated_case_count"},
    "code_component": {"code_file_count", "changed_entry_count"},
    "image_component": set(),
    "authority_component": {
        "blocking_gate_count",
        "pipeline_source_binding_count",
    },
}
_STATUS_FIELDS = {
    "source_component": {"status"},
    "lexical_index_component": {"status"},
    "graph_ontology_component": {"status"},
    "answer_component": {"status", "final_answer_acceptance_status"},
    "evaluation_component": {
        "status",
        "quality_gate_status",
        "operational_budget_status",
        "independent_holdout_status",
        "transfer_evaluation_status",
    },
    "code_component": {"status"},
    "image_component": {"status"},
    "authority_component": {"status", "methodology_ready_status"},
}
_STATUS_FIELDS["authority_component"].update(
    {
        "source_completeness_gate_status",
        "real_source_ablation_gate_status",
    }
)


class ExecutionFingerprintValidationError(RuntimeError):
    """Fail-closed error carrying only a stable safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class ExecutionFingerprintArtifacts:
    bundle: dict[str, Any]
    public_report: dict[str, Any]


def seal_safe_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical copy with a self-verifying artifact fingerprint."""

    sealed = dict(payload)
    sealed.pop(_HASH_FIELD, None)
    sealed[_HASH_FIELD] = _payload_fingerprint(sealed, _HASH_FIELD)
    return sealed


def current_runtime_binding_fingerprints() -> dict[str, str]:
    """Resolve the frozen runtime declarations without loading dense model bytes."""

    lexical_profile = load_issue56_target_mail_tokenizer_profile()
    dense_profile = issue56_target_dense_embedding_profile()
    runtime_binding = build_issue56_execution_component_binding(
        tokenizer_profile=lexical_profile,
        dense_profile=dense_profile,
    )
    evaluator_fingerprint = sha256_json(
        {
            "evaluator_id": EVALUATOR_ID,
            "case_count": CASE_COUNT,
            "result_kinds": [
                "owner_match",
                "no_match",
                "permission_denied",
            ],
        }
    )
    return {
        "lexical_profile_id": lexical_profile.tokenizer_id,
        "lexical_profile_fingerprint": lexical_profile.profile_fingerprint,
        "dense_model_id": dense_profile.model_id,
        "dense_model_revision": dense_profile.model_revision,
        "dense_profile_fingerprint": dense_profile.profile_fingerprint,
        "runtime_component_fingerprint": runtime_binding.execution_component_fingerprint,
        "runtime_method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        "graph_adapter_fingerprint": sha256_json(GRAPH_ADAPTER_ID),
        "source_graph_policy_fingerprint": sha256_json(SOURCE_GRAPH_POLICY_ID),
        "source_identifier_adapter_fingerprint": sha256_json(SOURCE_IDENTIFIER_ADAPTER_ID),
        "source_identifier_candidate_schema_fingerprint": sha256_json(
            {
                "artifact_id": SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
                "schema_version": SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
            }
        ),
        "source_identifier_extraction_policy_fingerprint": (
            SOURCE_BOUND_IDENTIFIER_EXTRACTION_POLICY_FINGERPRINT
        ),
        "source_identifier_resolution_policy_fingerprint": (
            SOURCE_IDENTIFIER_RESOLUTION_POLICY_FINGERPRINT
        ),
        "source_identifier_identity_scope_policy_fingerprint": (IDENTITY_SCOPE_POLICY_FINGERPRINT),
        "relation_type_hash_set_fingerprint": sha256_json(
            sorted(sha256_json(value) for value in GRAPH_RELATION_TYPES)
        ),
        "ontology_target_fingerprint": sha256_json(ONTOLOGY_TARGET),
        "answer_model_fingerprint": sha256_json(ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID),
        "answer_prompt_fingerprint": ISSUE56_DETERMINISTIC_ANSWER_PROMPT_FINGERPRINT,
        "answer_budget_fingerprint": EvidenceAnswerBudget().fingerprint,
        "evaluator_fingerprint": evaluator_fingerprint,
    }


def build_current_code_component(
    *,
    repository_root: Path,
    run_binding_fingerprint: str,
) -> dict[str, Any]:
    """Build a safe current-code attestation over bounded implementation scopes."""

    _require_sha256(run_binding_fingerprint, "component_run_binding_invalid")
    resolved_root = _resolved_repository_root(repository_root)
    commit = _git_output(resolved_root, ("rev-parse", "HEAD"))
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise ExecutionFingerprintValidationError("code_revision_attestation_unavailable")
    tree_fingerprint, file_count = _scoped_code_tree_fingerprint(resolved_root)
    status_bytes = _git_output_bytes(
        resolved_root,
        (
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *_CODE_DIRECTORY_SCOPES,
            *_CODE_FILE_SCOPES,
        ),
    )
    changed_entry_count = len([entry for entry in status_bytes.split(b"\0") if entry])
    script_path = resolved_root / "scripts" / "issue56_execution_fingerprint.py"
    script_fingerprint = _regular_file_sha256(
        script_path,
        resolved_root=resolved_root,
    )
    return seal_safe_artifact(
        {
            "artifact_id": CODE_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "run_binding_fingerprint": run_binding_fingerprint,
            "commit_fingerprint": sha256_json(commit),
            "code_tree_fingerprint": tree_fingerprint,
            "code_tree_scope_fingerprint": sha256_json(
                {
                    "directories": list(_CODE_DIRECTORY_SCOPES),
                    "files": list(_CODE_FILE_SCOPES),
                }
            ),
            "script_fingerprint": script_fingerprint,
            "code_file_count": file_count,
            "changed_entry_count": changed_entry_count,
        }
    )


def build_current_authority_component(
    *,
    repository_root: Path,
    run_binding_fingerprint: str,
) -> dict[str, Any]:
    """Bind the safe current executable methodology-authority projection."""

    _require_sha256(run_binding_fingerprint, "component_run_binding_invalid")
    authority = check_methodology_authority(repository_root=repository_root)
    if (
        not authority.authority_valid
        or authority.status not in {"blocked", "ready"}
        or authority.execution_fingerprint is None
        or authority.authority_state_fingerprint is None
    ):
        raise ExecutionFingerprintValidationError("authority_state_unavailable_or_invalid")
    blocking_gate_ids = set(authority.blocking_gate_ids)
    return seal_safe_artifact(
        {
            "artifact_id": AUTHORITY_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": authority.status,
            "run_binding_fingerprint": run_binding_fingerprint,
            "methodology_ready_status": ("passed" if authority.methodology_ready else "blocked"),
            "authority_state_fingerprint": authority.authority_state_fingerprint,
            "authority_execution_fingerprint": authority.execution_fingerprint,
            "blocking_gate_set_fingerprint": sha256_json(sorted(authority.blocking_gate_ids)),
            "blocking_gate_count": len(authority.blocking_gate_ids),
            "pipeline_source_binding_count": authority.pipeline_source_binding_count,
            "source_completeness_gate_status": (
                "blocked"
                if "source_completeness_compared_with_raw_oracle" in blocking_gate_ids
                else "passed"
            ),
            "real_source_ablation_gate_status": (
                "blocked" if "same_pipeline_real_source_ablation" in blocking_gate_ids else "passed"
            ),
        }
    )


def build_image_component(
    *,
    run_binding_fingerprint: str,
    image_id: str,
    image_metadata_fingerprint: str,
) -> dict[str, Any]:
    """Build the safe half of a host-observed canonical image attestation."""

    _require_sha256(run_binding_fingerprint, "component_run_binding_invalid")
    _require_sha256(image_id, "canonical_image_attestation_missing_or_invalid")
    _require_sha256(
        image_metadata_fingerprint,
        "canonical_image_attestation_missing_or_invalid",
    )
    if (
        image_id != FROZEN_CANONICAL_IMAGE_ID
        or image_metadata_fingerprint != FROZEN_CANONICAL_IMAGE_METADATA_FINGERPRINT
    ):
        raise ExecutionFingerprintValidationError("canonical_image_attestation_mismatch")
    return seal_safe_artifact(
        {
            "artifact_id": IMAGE_COMPONENT_ID,
            "schema_version": SCHEMA_VERSION,
            "status": "passed",
            "run_binding_fingerprint": run_binding_fingerprint,
            "image_reference_fingerprint": sha256_json(CANONICAL_IMAGE_REFERENCE),
            "image_id": image_id,
            "image_metadata_fingerprint": image_metadata_fingerprint,
            "attestor_fingerprint": sha256_json(IMAGE_ATTESTOR_ID),
        }
    )


def create_execution_fingerprint_artifacts(
    *,
    input_payload: Mapping[str, Any],
    uat_report_path: Path,
    expected_uat_report_fingerprint: str,
    repository_root: Path,
    canonical_image_id: str | None,
    canonical_image_metadata_fingerprint: str | None,
) -> ExecutionFingerprintArtifacts:
    """Validate all inputs and return a blocked-or-passed safe bundle."""

    validated = _validate_input_payload(
        input_payload,
        repository_root=repository_root,
        canonical_image_id=canonical_image_id,
        canonical_image_metadata_fingerprint=canonical_image_metadata_fingerprint,
    )
    source = validated["source_component"]
    lexical = validated["lexical_index_component"]
    graph = validated["graph_ontology_component"]
    answer = validated["answer_component"]
    evaluation = validated["evaluation_component"]
    code = validated["code_component"]
    image = validated["image_component"]
    authority = validated["authority_component"]
    uat_binding = _load_and_validate_completed_uat_report(
        report_path=uat_report_path,
        expected_report_fingerprint=expected_uat_report_fingerprint,
        validated_components=validated,
        repository_root=repository_root,
        canonical_image_id=canonical_image_id,
        canonical_image_metadata_fingerprint=canonical_image_metadata_fingerprint,
    )

    blocker_ids = _readiness_blockers(validated)
    component_artifact_fingerprints = {
        name.removesuffix("_component"): validated[name][_HASH_FIELD]
        for name in REQUIRED_COMPONENT_NAMES
    }
    bound_fingerprints = {
        "source_snapshot": source["source_snapshot_fingerprint"],
        "completeness_report": source["completeness_report_fingerprint"],
        "source_inventory": source["source_inventory_fingerprint"],
        "lexical_profile": lexical["lexical_profile_fingerprint"],
        "dense_profile": lexical["dense_profile_fingerprint"],
        "runtime_component": lexical["runtime_component_fingerprint"],
        "index": lexical["index_fingerprint"],
        "graph_artifact": graph["graph_artifact_fingerprint"],
        "graph_adapter": graph["graph_adapter_fingerprint"],
        "source_graph_policy": graph["source_graph_policy_fingerprint"],
        "source_identifier_adapter": graph["source_identifier_adapter_fingerprint"],
        "graph_relation_type_set": graph["relation_type_hash_set_fingerprint"],
        "source_identifier_candidate_artifact": graph[
            "source_identifier_candidate_artifact_fingerprint"
        ],
        "source_identifier_candidate_binding": graph[
            "source_identifier_candidate_binding_fingerprint"
        ],
        "source_identifier_candidate_schema": graph[
            "source_identifier_candidate_schema_fingerprint"
        ],
        "source_identifier_identity_scope_mode": graph[
            "source_identifier_identity_scope_mode_fingerprint"
        ],
        "source_identifier_identity_scope": graph["source_identifier_identity_scope_fingerprint"],
        "source_identifier_identity_scope_binding": graph[
            "source_identifier_identity_scope_binding_fingerprint"
        ],
        "source_identifier_identity_scope_attestation_bytes": graph[
            "source_identifier_identity_scope_attestation_byte_fingerprint"
        ],
        "source_identifier_identity_scope_attestation": graph[
            "source_identifier_identity_scope_attestation_fingerprint"
        ],
        "source_identifier_identity_scope_policy": graph[
            "source_identifier_identity_scope_policy_fingerprint"
        ],
        "source_identifier_operator_approval": graph[
            "source_identifier_operator_approval_fingerprint"
        ],
        "source_identifier_mode_approval": graph["source_identifier_mode_approval_fingerprint"],
        "source_identifier_extraction_policy": graph[
            "source_identifier_extraction_policy_fingerprint"
        ],
        "source_identifier_resolution_policy": graph[
            "source_identifier_resolution_policy_fingerprint"
        ],
        "source_identifier_identity_scope_graph_binding_set": graph[
            "source_identifier_identity_scope_graph_binding_set_fingerprint"
        ],
        "complete_identifier_mention_batch": graph["complete_identifier_mention_batch_fingerprint"],
        "selected_identifier_mention_batch": graph["selected_identifier_mention_batch_fingerprint"],
        "complete_identifier_mention_set": graph[
            "complete_identifier_mention_fingerprint_set_hash"
        ],
        "authorized_identifier_mention_set": graph[
            "authorized_identifier_mention_fingerprint_set_hash"
        ],
        "complete_identifier_resolution": graph["complete_identifier_resolution_fingerprint"],
        "selected_identifier_resolution": graph["selected_identifier_resolution_fingerprint"],
        "graph_identifier_resolution_set": graph["identifier_resolution_fingerprint_set_hash"],
        "ontology_artifact": graph["ontology_artifact_fingerprint"],
        "ontology_target": graph["ontology_target_fingerprint"],
        "answer_model": answer["answer_model_fingerprint"],
        "answer_prompt": answer["answer_prompt_fingerprint"],
        "answer_budget": answer["answer_budget_fingerprint"],
        "evaluator": evaluation["evaluator_fingerprint"],
        "quality_gate_report": evaluation["quality_gate_report_fingerprint"],
        "uat_report": uat_binding["report_fingerprint"],
        "uat_content": uat_binding["content_fingerprint"],
        "uat_run": uat_binding["run_fingerprint"],
        "runtime_method": evaluation["runtime_method_fingerprint"],
        "code_commit": code["commit_fingerprint"],
        "code_tree": code["code_tree_fingerprint"],
        "code_tree_scope": code["code_tree_scope_fingerprint"],
        "script": code["script_fingerprint"],
        "image_id": image["image_id"],
        "image_metadata": image["image_metadata_fingerprint"],
        "image_attestor": image["attestor_fingerprint"],
        "authority_state": authority["authority_state_fingerprint"],
        "authority_execution": authority["authority_execution_fingerprint"],
        "authority_blocking_gate_set": authority["blocking_gate_set_fingerprint"],
    }
    counts = {
        "source_item_count": source["source_item_count"],
        "observation_count": source["observation_count"],
        "unexplained_loss_count": source["unexplained_loss_count"],
        "index_count": lexical["index_count"],
        "ascii_fallback_count": lexical["ascii_fallback_count"],
        "graph_node_count": graph["graph_node_count"],
        "graph_edge_count": graph["graph_edge_count"],
        "unresolved_evidence_hop_count": graph["unresolved_evidence_hop_count"],
        "complete_identifier_mention_count": graph["complete_identifier_mention_count"],
        "selected_identifier_mention_count": graph["selected_identifier_mention_count"],
        "authorized_identifier_mention_count": graph["authorized_identifier_mention_count"],
        "complete_resolved_identifier_candidate_count": graph[
            "complete_resolved_identifier_candidate_count"
        ],
        "selected_resolved_identifier_candidate_count": graph[
            "selected_resolved_identifier_candidate_count"
        ],
        "answer_count": answer["answer_count"],
        "evaluated_case_count": evaluation["evaluated_case_count"],
        "code_file_count": code["code_file_count"],
        "changed_entry_count": code["changed_entry_count"],
        "authority_blocking_gate_count": authority["blocking_gate_count"],
        "pipeline_source_binding_count": authority["pipeline_source_binding_count"],
        "uat_report_count": 1,
    }
    statuses = {
        "source_completeness": source["status"],
        "lexical_index": lexical["status"],
        "graph_ontology": graph["status"],
        "answer_component": answer["status"],
        "final_answer_acceptance": answer["final_answer_acceptance_status"],
        "evaluation_component": evaluation["status"],
        "uat_quality_gate": evaluation["quality_gate_status"],
        "operational_budget": evaluation["operational_budget_status"],
        "independent_holdout": evaluation["independent_holdout_status"],
        "transfer_evaluation": evaluation["transfer_evaluation_status"],
        "code_attestation": code["status"],
        "image_attestation": image["status"],
        "methodology_authority": authority["status"],
        "methodology_ready": authority["methodology_ready_status"],
        "source_completeness_authority_gate": authority["source_completeness_gate_status"],
        "real_source_ablation_authority_gate": authority["real_source_ablation_gate_status"],
    }
    execution_fingerprint = sha256_json(
        {
            "run_binding_fingerprint": validated["run_binding_fingerprint"],
            "source_binding_fingerprint": source["source_binding_fingerprint"],
            "component_artifact_fingerprints": component_artifact_fingerprints,
            "bound_fingerprints": bound_fingerprints,
        }
    )
    status = "passed" if not blocker_ids else "blocked"
    bundle = {
        "artifact_id": BUNDLE_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "run_binding_fingerprint": validated["run_binding_fingerprint"],
        "source_binding_fingerprint": source["source_binding_fingerprint"],
        "execution_fingerprint": execution_fingerprint,
        "component_artifact_fingerprints": component_artifact_fingerprints,
        "bound_fingerprints": bound_fingerprints,
        "counts": counts,
        "statuses": statuses,
        "blocking_status_ids": blocker_ids,
        "blocking_status_fingerprint": sha256_json(blocker_ids),
    }
    bundle["bundle_fingerprint"] = _payload_fingerprint(
        bundle,
        "bundle_fingerprint",
    )
    _validate_bundle(bundle)

    component_statuses = [validated[name]["status"] for name in REQUIRED_COMPONENT_NAMES]
    public_report = {
        "artifact_id": REPORT_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "acceptance_status": status,
        "bundle_round_trip_status": "passed",
        "public_report_round_trip_status": "passed",
        "run_binding_fingerprint": validated["run_binding_fingerprint"],
        "input_artifact_fingerprint": validated[_HASH_FIELD],
        "execution_fingerprint": execution_fingerprint,
        "bundle_fingerprint": bundle["bundle_fingerprint"],
        "component_set_fingerprint": sha256_json(component_artifact_fingerprints),
        "component_count": len(component_artifact_fingerprints),
        "accepted_component_count": component_statuses.count("passed"),
        "blocked_component_count": len(component_statuses) - component_statuses.count("passed"),
        "blocking_status_ids": blocker_ids,
        "blocking_status_fingerprint": sha256_json(blocker_ids),
        "authority_state_fingerprint": authority["authority_state_fingerprint"],
        "authority_execution_fingerprint": authority["authority_execution_fingerprint"],
        "uat_report_fingerprint": uat_binding["report_fingerprint"],
        "uat_run_fingerprint": uat_binding["run_fingerprint"],
        "source_item_count": source["source_item_count"],
        "observation_count": source["observation_count"],
        "index_count": lexical["index_count"],
        "graph_node_count": graph["graph_node_count"],
        "graph_edge_count": graph["graph_edge_count"],
        "selected_identifier_mention_count": graph["selected_identifier_mention_count"],
        "authorized_identifier_mention_count": graph["authorized_identifier_mention_count"],
        "selected_resolved_identifier_candidate_count": graph[
            "selected_resolved_identifier_candidate_count"
        ],
        "evaluated_case_count": evaluation["evaluated_case_count"],
    }
    public_report["report_fingerprint"] = _payload_fingerprint(
        public_report,
        "report_fingerprint",
    )
    _validate_public_report(public_report)
    return ExecutionFingerprintArtifacts(
        bundle=bundle,
        public_report=public_report,
    )


def persist_execution_fingerprint_artifacts(
    *,
    artifacts: ExecutionFingerprintArtifacts,
    bundle_output: Path,
    public_output: Path,
) -> ExecutionFingerprintArtifacts:
    """Persist immutable artifacts and verify exact JSON round trips."""

    persisted_bundle = _persist_immutable_json(
        bundle_output,
        artifacts.bundle,
        validator=_validate_bundle,
    )
    persisted_report = _persist_immutable_json(
        public_output,
        artifacts.public_report,
        validator=_validate_public_report,
    )
    if persisted_bundle != artifacts.bundle or persisted_report != artifacts.public_report:
        raise ExecutionFingerprintValidationError("artifact_round_trip_mismatch")
    return ExecutionFingerprintArtifacts(
        bundle=persisted_bundle,
        public_report=persisted_report,
    )


def load_and_validate_bundle(path: Path) -> dict[str, Any]:
    """Load one persisted safe bundle and fail closed on any drift."""

    payload = _read_json_object(path)
    _validate_bundle(payload)
    return payload


def _load_and_validate_completed_uat_report(
    *,
    report_path: Path,
    expected_report_fingerprint: str,
    validated_components: Mapping[str, Any],
    repository_root: Path,
    canonical_image_id: str | None,
    canonical_image_metadata_fingerprint: str | None,
) -> dict[str, str]:
    _require_sha256(
        expected_report_fingerprint,
        "expected_uat_report_fingerprint_missing_or_invalid",
    )
    report_bytes, report = _read_json_object_with_bytes(
        report_path,
        maximum_bytes=_MAX_UAT_REPORT_BYTES,
        reason_code="uat_report_missing_or_invalid",
    )
    report_fingerprint = _sha256_bytes(report_bytes)
    if report_fingerprint != expected_report_fingerprint:
        raise ExecutionFingerprintValidationError("uat_report_fingerprint_mismatch")
    if (
        report.get("artifact_id") != UAT_ARTIFACT_ID
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("diagnostic_label") != UAT_DEVELOPMENT_BOUNDARY_ID
    ):
        raise ExecutionFingerprintValidationError("uat_report_identity_invalid")
    if report.get("execution_status") != "passed" or report.get("e2e_executed") is not True:
        raise ExecutionFingerprintValidationError("uat_execution_not_passed")
    quality_gate_status = report.get("quality_gate_status")
    expected_report_status = {
        "passed": "passed",
        "failed": "quality_failed",
        "blocked": "blocked",
    }.get(quality_gate_status)
    if expected_report_status is None or report.get("status") != expected_report_status:
        raise ExecutionFingerprintValidationError("uat_quality_status_invalid")

    manifest_seal = _require_uat_mapping(report, "manifest_seal")
    if (
        manifest_seal.get("sealed_before_execution") is not True
        or manifest_seal.get("unchanged_after_execution") is not True
        or manifest_seal.get("expected_seal_matches") is not True
    ):
        raise ExecutionFingerprintValidationError("uat_manifest_seal_invalid")
    _require_sha256(
        manifest_seal.get("manifest_byte_hash"),
        "uat_manifest_seal_invalid",
    )

    source_component = validated_components["source_component"]
    lexical_component = validated_components["lexical_index_component"]
    graph_component = validated_components["graph_ontology_component"]
    answer_component = validated_components["answer_component"]
    evaluation_component = validated_components["evaluation_component"]
    authority_component = validated_components["authority_component"]

    source = _require_uat_mapping(report, "source")
    _require_exact_uat_binding(
        source,
        "source_binding_fingerprint",
        source_component["source_binding_fingerprint"],
        "uat_source_binding_mismatch",
    )
    _require_exact_uat_binding(
        source,
        "source_snapshot_fingerprint",
        source_component["source_snapshot_fingerprint"],
        "uat_source_snapshot_mismatch",
    )
    observation_count = _require_uat_nonnegative_int(
        source,
        "loaded_observation_count",
        "uat_source_observation_count_invalid",
    )
    if (
        observation_count != source_component["observation_count"]
        or _require_uat_nonnegative_int(
            source,
            "selected_observation_count",
            "uat_source_observation_count_invalid",
        )
        != observation_count
        or _require_uat_nonnegative_int(
            source,
            "source_observation_hash_count",
            "uat_source_observation_count_invalid",
        )
        != observation_count
    ):
        raise ExecutionFingerprintValidationError("uat_source_observation_count_mismatch")
    _require_sha256(
        source.get("source_observation_hash_set_fingerprint"),
        "uat_source_snapshot_invalid",
    )
    if source.get("manifest_bundle_identity_matches") is not True:
        raise ExecutionFingerprintValidationError("uat_source_identity_invalid")
    if (
        _require_uat_nonnegative_int(
            source,
            "case_count",
            "uat_case_count_invalid",
        )
        != evaluation_component["evaluated_case_count"]
    ):
        raise ExecutionFingerprintValidationError("uat_case_count_mismatch")
    source_identifier_binding = _require_uat_mapping(
        source,
        "source_identifier_candidate_binding",
    )
    source_identifier_fingerprint_bindings = {
        "source_artifact_fingerprint": graph_component[
            "source_identifier_candidate_artifact_fingerprint"
        ],
        "binding_fingerprint": graph_component["source_identifier_candidate_binding_fingerprint"],
        "candidate_artifact_schema_fingerprint": graph_component[
            "source_identifier_candidate_schema_fingerprint"
        ],
        "identity_scope_mode_fingerprint": graph_component[
            "source_identifier_identity_scope_mode_fingerprint"
        ],
        "identity_scope_fingerprint": graph_component[
            "source_identifier_identity_scope_fingerprint"
        ],
        "identity_scope_binding_fingerprint": graph_component[
            "source_identifier_identity_scope_binding_fingerprint"
        ],
        "identity_scope_attestation_byte_sha256": graph_component[
            "source_identifier_identity_scope_attestation_byte_fingerprint"
        ],
        "identity_scope_attestation_fingerprint": graph_component[
            "source_identifier_identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": graph_component[
            "source_identifier_identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": graph_component[
            "source_identifier_operator_approval_fingerprint"
        ],
        "mode_approval_fingerprint": graph_component["source_identifier_mode_approval_fingerprint"],
        "extraction_policy_fingerprint": graph_component[
            "source_identifier_extraction_policy_fingerprint"
        ],
        "resolution_policy_fingerprint": graph_component[
            "source_identifier_resolution_policy_fingerprint"
        ],
        "complete_mention_batch_fingerprint": graph_component[
            "complete_identifier_mention_batch_fingerprint"
        ],
        "selected_mention_batch_fingerprint": graph_component[
            "selected_identifier_mention_batch_fingerprint"
        ],
        "complete_resolution_fingerprint": graph_component[
            "complete_identifier_resolution_fingerprint"
        ],
        "selected_resolution_fingerprint": graph_component[
            "selected_identifier_resolution_fingerprint"
        ],
        "source_graph_policy_fingerprint": graph_component["source_graph_policy_fingerprint"],
        "source_identifier_adapter_fingerprint": graph_component[
            "source_identifier_adapter_fingerprint"
        ],
        "relation_type_hash_set_fingerprint": graph_component["relation_type_hash_set_fingerprint"],
    }
    for field_name, expected_value in source_identifier_fingerprint_bindings.items():
        _require_exact_uat_binding(
            source_identifier_binding,
            field_name,
            expected_value,
            f"uat_source_identifier_binding_mismatch_{field_name}",
        )
    source_identifier_count_bindings = {
        "complete_mention_count": graph_component["complete_identifier_mention_count"],
        "selected_mention_count": graph_component["selected_identifier_mention_count"],
        "complete_resolved_candidate_count": graph_component[
            "complete_resolved_identifier_candidate_count"
        ],
        "selected_resolved_candidate_count": graph_component[
            "selected_resolved_identifier_candidate_count"
        ],
        "overflow_count": 0,
    }
    for field_name, expected_value in source_identifier_count_bindings.items():
        if (
            _require_uat_nonnegative_int(
                source_identifier_binding,
                field_name,
                f"uat_source_identifier_count_invalid_{field_name}",
            )
            != expected_value
        ):
            raise ExecutionFingerprintValidationError(
                f"uat_source_identifier_count_mismatch_{field_name}"
            )
    if (
        source_identifier_binding.get("status") != "sealed_passed"
        or source_identifier_binding.get("binding_id") != SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID
        or source_identifier_binding.get("candidate_artifact_schema_version")
        != SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION
        or source_identifier_binding.get("candidate_graph_only") is not True
        or source_identifier_binding.get("canonical_write_allowed") is not False
        or any(
            legacy_field in source_identifier_binding
            for legacy_field in (
                "tenant_id",
                "tenant_workspace_binding",
                "tenant_workspace_fingerprint",
            )
        )
    ):
        raise ExecutionFingerprintValidationError("uat_source_identifier_claim_boundary_invalid")
    identity_scope_mode = source_identifier_binding.get("identity_scope_mode_status")
    if identity_scope_mode not in {
        TENANT_WORKSPACE_IDENTITY_SCOPE_MODE,
        WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    }:
        raise ExecutionFingerprintValidationError("uat_source_identifier_identity_scope_invalid")
    expected_schema_fingerprint = sha256_json(
        {
            "artifact_id": SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_ID,
            "schema_version": SOURCE_IDENTIFIER_CANDIDATE_SCHEMA_VERSION,
        }
    )
    if (
        source_identifier_binding.get("candidate_artifact_schema_fingerprint")
        != expected_schema_fingerprint
        or graph_component["source_identifier_candidate_schema_fingerprint"]
        != expected_schema_fingerprint
        or source_identifier_binding.get("identity_scope_mode_fingerprint")
        != sha256_json(identity_scope_mode)
    ):
        raise ExecutionFingerprintValidationError("uat_source_identifier_identity_scope_invalid")
    expected_mode_approval_fingerprint = sha256_json(
        {
            "identity_scope_mode": identity_scope_mode,
            "operator_approval_fingerprint": source_identifier_binding.get(
                "operator_approval_fingerprint"
            ),
            "spec_approval_fingerprint": source_identifier_binding.get("spec_approval_fingerprint"),
        }
    )
    if (
        source_identifier_binding.get("mode_approval_fingerprint")
        != expected_mode_approval_fingerprint
        or (
            identity_scope_mode == WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
            and not isinstance(
                source_identifier_binding.get("spec_approval_fingerprint"),
                str,
            )
        )
        or (
            identity_scope_mode == TENANT_WORKSPACE_IDENTITY_SCOPE_MODE
            and "spec_approval_fingerprint" in source_identifier_binding
        )
    ):
        raise ExecutionFingerprintValidationError(
            "uat_source_identifier_identity_scope_approval_invalid"
        )
    _require_exact_uat_binding(
        source_identifier_binding,
        "candidate_admission_profile_fingerprint",
        lexical_component["lexical_profile_fingerprint"],
        "uat_source_identifier_profile_mismatch",
    )

    shared = _require_uat_mapping(report, "shared_pipeline")
    expected_shared_bindings = {
        "lexical_profile_fingerprint": lexical_component["lexical_profile_fingerprint"],
        "query_lexical_profile_fingerprint": lexical_component["query_profile_fingerprint"],
        "evidence_lexical_profile_fingerprint": lexical_component["evidence_profile_fingerprint"],
        "dense_profile_fingerprint": lexical_component["dense_profile_fingerprint"],
        "execution_component_fingerprint": lexical_component["runtime_component_fingerprint"],
        "permission_scoped_index_set_fingerprint": lexical_component["index_fingerprint"],
        "runtime_method_fingerprint": evaluation_component["runtime_method_fingerprint"],
        "graph_adapter_fingerprint": graph_component["graph_adapter_fingerprint"],
        "source_graph_policy_fingerprint": graph_component["source_graph_policy_fingerprint"],
        "source_identifier_adapter_fingerprint": graph_component[
            "source_identifier_adapter_fingerprint"
        ],
        "relation_type_hash_set_fingerprint": graph_component["relation_type_hash_set_fingerprint"],
        "ontology_target_fingerprint": graph_component["ontology_target_fingerprint"],
        "answer_model_fingerprint": answer_component["answer_model_fingerprint"],
        "answer_prompt_fingerprint": answer_component["answer_prompt_fingerprint"],
        "answer_budget_fingerprint": answer_component["answer_budget_fingerprint"],
        "evaluator_fingerprint": evaluation_component["evaluator_fingerprint"],
    }
    for field_name, expected_value in expected_shared_bindings.items():
        _require_exact_uat_binding(
            shared,
            field_name,
            expected_value,
            f"uat_pipeline_binding_mismatch_{field_name}",
        )
    current_runtime = current_runtime_binding_fingerprints()
    for field_name in (
        "lexical_profile_id",
        "dense_model_id",
        "dense_model_revision",
    ):
        _require_exact_uat_binding(
            shared,
            field_name,
            current_runtime[field_name],
            f"uat_pipeline_binding_mismatch_{field_name}",
        )
    if shared.get("runtime_method_id") != ISSUE56_TARGET_RUNTIME_METHOD_ID:
        raise ExecutionFingerprintValidationError("uat_runtime_method_id_mismatch")
    if shared.get("all_arms_share_answer_model_prompt_budget_evaluator") is not True:
        raise ExecutionFingerprintValidationError("uat_shared_pipeline_binding_invalid")
    if _require_uat_nonnegative_int(
        shared,
        "execution_component_fingerprint_count",
        "uat_execution_component_binding_invalid",
    ) != 1 or shared.get("execution_component_fingerprint_set_hash") != sha256_json(
        [lexical_component["runtime_component_fingerprint"]]
    ):
        raise ExecutionFingerprintValidationError("uat_execution_component_binding_invalid")
    if (
        _require_uat_nonnegative_int(
            shared,
            "permission_scoped_index_count",
            "uat_index_binding_invalid",
        )
        != lexical_component["index_count"]
    ):
        raise ExecutionFingerprintValidationError("uat_index_binding_invalid")

    graph_builds = _require_uat_mapping(shared, "graph_builds")
    _require_exact_uat_binding(
        graph_builds,
        "build_fingerprint_set_hash",
        graph_component["graph_artifact_fingerprint"],
        "uat_graph_binding_mismatch",
    )
    _require_exact_uat_binding(
        graph_builds,
        "ontology_revision_fingerprint_set_hash",
        graph_component["ontology_artifact_fingerprint"],
        "uat_ontology_binding_mismatch",
    )
    graph_build_bindings = {
        "graph_adapter_fingerprint": graph_component["graph_adapter_fingerprint"],
        "source_graph_policy_fingerprint": graph_component["source_graph_policy_fingerprint"],
        "source_identifier_adapter_fingerprint": graph_component[
            "source_identifier_adapter_fingerprint"
        ],
        "relation_type_hash_set_fingerprint": graph_component["relation_type_hash_set_fingerprint"],
        "source_identifier_candidate_artifact_fingerprint": graph_component[
            "source_identifier_candidate_artifact_fingerprint"
        ],
        "source_identifier_candidate_binding_fingerprint": graph_component[
            "source_identifier_candidate_binding_fingerprint"
        ],
        "candidate_artifact_schema_fingerprint": graph_component[
            "source_identifier_candidate_schema_fingerprint"
        ],
        "identity_scope_mode_fingerprint": graph_component[
            "source_identifier_identity_scope_mode_fingerprint"
        ],
        "identity_scope_fingerprint": graph_component[
            "source_identifier_identity_scope_fingerprint"
        ],
        "identity_scope_binding_fingerprint": graph_component[
            "source_identifier_identity_scope_binding_fingerprint"
        ],
        "identity_scope_attestation_byte_sha256": graph_component[
            "source_identifier_identity_scope_attestation_byte_fingerprint"
        ],
        "identity_scope_attestation_fingerprint": graph_component[
            "source_identifier_identity_scope_attestation_fingerprint"
        ],
        "identity_scope_policy_fingerprint": graph_component[
            "source_identifier_identity_scope_policy_fingerprint"
        ],
        "operator_approval_fingerprint": graph_component[
            "source_identifier_operator_approval_fingerprint"
        ],
        "mode_approval_fingerprint": graph_component["source_identifier_mode_approval_fingerprint"],
        "extraction_policy_fingerprint": graph_component[
            "source_identifier_extraction_policy_fingerprint"
        ],
        "resolution_policy_fingerprint": graph_component[
            "source_identifier_resolution_policy_fingerprint"
        ],
        "identity_scope_graph_binding_fingerprint_set_hash": graph_component[
            "source_identifier_identity_scope_graph_binding_set_fingerprint"
        ],
        "complete_identifier_mention_fingerprint_set_hash": graph_component[
            "complete_identifier_mention_fingerprint_set_hash"
        ],
        "authorized_identifier_mention_fingerprint_set_hash": graph_component[
            "authorized_identifier_mention_fingerprint_set_hash"
        ],
        "identifier_resolution_fingerprint_set_hash": graph_component[
            "identifier_resolution_fingerprint_set_hash"
        ],
        "selected_identifier_mention_batch_fingerprint": graph_component[
            "selected_identifier_mention_batch_fingerprint"
        ],
        "selected_identifier_resolution_fingerprint": graph_component[
            "selected_identifier_resolution_fingerprint"
        ],
    }
    for field_name, expected_value in graph_build_bindings.items():
        _require_exact_uat_binding(
            graph_builds,
            field_name,
            expected_value,
            f"uat_graph_binding_mismatch_{field_name}",
        )
    graph_node_count = _require_uat_nonnegative_int(
        graph_builds,
        "observation_node_count",
        "uat_graph_count_invalid",
    ) + _require_uat_nonnegative_int(
        graph_builds,
        "entity_node_count",
        "uat_graph_count_invalid",
    )
    if (
        graph_node_count != graph_component["graph_node_count"]
        or _require_uat_nonnegative_int(
            graph_builds,
            "edge_count",
            "uat_graph_count_invalid",
        )
        != graph_component["graph_edge_count"]
    ):
        raise ExecutionFingerprintValidationError("uat_graph_count_mismatch")
    graph_build_count_bindings = {
        "identifier_mention_count": graph_component["selected_identifier_mention_count"],
        "authorized_identifier_mention_count": graph_component[
            "authorized_identifier_mention_count"
        ],
        "selected_resolved_candidate_count": graph_component[
            "selected_resolved_identifier_candidate_count"
        ],
    }
    for field_name, expected_value in graph_build_count_bindings.items():
        if (
            _require_uat_nonnegative_int(
                graph_builds,
                field_name,
                f"uat_graph_count_invalid_{field_name}",
            )
            != expected_value
        ):
            raise ExecutionFingerprintValidationError(f"uat_graph_count_mismatch_{field_name}")
    if (
        graph_builds.get("candidate_graph_only") is not True
        or graph_builds.get("human_review_complete") is not False
    ):
        raise ExecutionFingerprintValidationError("uat_graph_candidate_boundary_invalid")

    if shared.get("answer_model_id") != ISSUE56_DETERMINISTIC_ANSWER_MODEL_ID:
        raise ExecutionFingerprintValidationError("uat_answer_model_id_mismatch")
    if shared.get("evaluator_id") != EVALUATOR_ID:
        raise ExecutionFingerprintValidationError("uat_evaluator_id_mismatch")
    quality_gate = _require_uat_mapping(report, "quality_gate")
    if (
        quality_gate.get("status") != quality_gate_status
        or evaluation_component["quality_gate_status"] != quality_gate_status
        or evaluation_component["quality_gate_report_fingerprint"] != sha256_json(quality_gate)
    ):
        raise ExecutionFingerprintValidationError("uat_quality_gate_binding_mismatch")

    run_fingerprint = report.get("diagnostic_run_fingerprint")
    _require_sha256(run_fingerprint, "uat_run_fingerprint_missing_or_invalid")
    content_fingerprint = sha256_json(report)
    expected_evaluation_bindings = {
        "uat_report_fingerprint": report_fingerprint,
        "uat_content_fingerprint": content_fingerprint,
        "uat_run_fingerprint": run_fingerprint,
    }
    for field_name, expected_value in expected_evaluation_bindings.items():
        if evaluation_component[field_name] != expected_value:
            raise ExecutionFingerprintValidationError(
                f"uat_evaluation_binding_mismatch_{field_name}"
            )

    execution_environment = _require_uat_mapping(report, "execution_environment")
    uat_run_binding = source_component["source_binding_fingerprint"]
    expected_code = build_current_code_component(
        repository_root=repository_root,
        run_binding_fingerprint=uat_run_binding,
    )
    expected_authority = build_current_authority_component(
        repository_root=repository_root,
        run_binding_fingerprint=uat_run_binding,
    )
    if canonical_image_id is None or canonical_image_metadata_fingerprint is None:
        raise ExecutionFingerprintValidationError("canonical_image_attestation_missing_or_invalid")
    expected_image = build_image_component(
        run_binding_fingerprint=uat_run_binding,
        image_id=canonical_image_id,
        image_metadata_fingerprint=canonical_image_metadata_fingerprint,
    )
    expected_environment_bindings = {
        "attestation_run_binding_fingerprint": uat_run_binding,
        "code_attestation_fingerprint": expected_code[_HASH_FIELD],
        "code_tree_fingerprint": expected_code["code_tree_fingerprint"],
        "code_tree_scope_fingerprint": expected_code["code_tree_scope_fingerprint"],
        "image_attestation_fingerprint": expected_image[_HASH_FIELD],
        "image_reference_fingerprint": expected_image["image_reference_fingerprint"],
        "image_id": expected_image["image_id"],
        "image_metadata_fingerprint": expected_image["image_metadata_fingerprint"],
        "authority_attestation_fingerprint": expected_authority[_HASH_FIELD],
        "authority_state_fingerprint": expected_authority["authority_state_fingerprint"],
        "authority_execution_fingerprint": expected_authority["authority_execution_fingerprint"],
        "authority_blocking_gate_set_fingerprint": expected_authority[
            "blocking_gate_set_fingerprint"
        ],
        "source_completeness_gate_status": expected_authority["source_completeness_gate_status"],
        "real_source_ablation_gate_status": expected_authority["real_source_ablation_gate_status"],
        "methodology_ready_status": expected_authority["methodology_ready_status"],
    }
    for field_name, expected_value in expected_environment_bindings.items():
        _require_exact_uat_binding(
            execution_environment,
            field_name,
            expected_value,
            f"uat_execution_environment_mismatch_{field_name}",
        )
    if (
        _require_uat_nonnegative_int(
            execution_environment,
            "authority_blocking_gate_count",
            "uat_execution_environment_invalid",
        )
        != expected_authority["blocking_gate_count"]
    ):
        raise ExecutionFingerprintValidationError("uat_execution_environment_invalid")

    claim_boundary = _require_uat_mapping(report, "claim_boundary")
    required_false_claims = (
        "independent_holdout",
        "methodology_complete",
        "issue56_complete",
        "production_ready",
        "supports_arm_superiority_claim",
    )
    if any(claim_boundary.get(field_name) is not False for field_name in required_false_claims):
        raise ExecutionFingerprintValidationError("uat_claim_boundary_invalid")
    if (
        claim_boundary.get("source_identifier_candidate_artifact_bound") is not True
        or claim_boundary.get("source_backed_candidate_graph_v2_bound") is not True
    ):
        raise ExecutionFingerprintValidationError("uat_source_identifier_claim_boundary_invalid")
    if authority_component["source_completeness_gate_status"] != "passed" and (
        source.get("source_complete") is not False
        or claim_boundary.get("source_complete") is not False
        or claim_boundary.get("methodology_ready") is not False
    ):
        raise ExecutionFingerprintValidationError("uat_source_completeness_readiness_claim_invalid")
    if authority_component["real_source_ablation_gate_status"] != "passed" and (
        claim_boundary.get("real_source_authority_gate_passed") is not False
        or claim_boundary.get("methodology_ready") is not False
    ):
        raise ExecutionFingerprintValidationError(
            "uat_real_source_ablation_readiness_claim_invalid"
        )
    _assert_completed_uat_public_safe(report)
    return {
        "report_fingerprint": report_fingerprint,
        "content_fingerprint": content_fingerprint,
        "run_fingerprint": run_fingerprint,
    }


def _require_uat_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    item = value.get(field_name)
    if not isinstance(item, Mapping):
        raise ExecutionFingerprintValidationError(f"uat_{field_name}_missing_or_invalid")
    return item


def _require_exact_uat_binding(
    value: Mapping[str, Any],
    field_name: str,
    expected_value: Any,
    reason_code: str,
) -> None:
    if field_name not in value or value[field_name] != expected_value:
        raise ExecutionFingerprintValidationError(reason_code)


def _require_uat_nonnegative_int(
    value: Mapping[str, Any],
    field_name: str,
    reason_code: str,
) -> int:
    item = value.get(field_name)
    if type(item) is not int or item < 0:
        raise ExecutionFingerprintValidationError(reason_code)
    return item


def _validate_input_payload(
    input_payload: Mapping[str, Any],
    *,
    repository_root: Path,
    canonical_image_id: str | None,
    canonical_image_metadata_fingerprint: str | None,
) -> dict[str, Any]:
    if type(input_payload) is not dict:
        raise ExecutionFingerprintValidationError("input_artifact_schema_invalid")
    missing = set(REQUIRED_COMPONENT_NAMES).difference(input_payload)
    if missing:
        raise ExecutionFingerprintValidationError("component_missing")
    if set(input_payload) != _TOP_LEVEL_KEYS:
        raise ExecutionFingerprintValidationError("input_artifact_schema_invalid")
    if (
        input_payload.get("artifact_id") != INPUT_ARTIFACT_ID
        or input_payload.get("schema_version") != SCHEMA_VERSION
        or input_payload.get("status") != "candidate"
    ):
        raise ExecutionFingerprintValidationError("input_artifact_schema_invalid")
    _require_sha256(
        input_payload.get("run_binding_fingerprint"),
        "component_run_binding_invalid",
    )
    _validate_artifact_fingerprint(
        input_payload,
        reason_code="input_artifact_fingerprint_invalid",
    )
    try:
        assert_no_public_raw_references(
            input_payload,
            "issue56_execution_fingerprint_inputs",
        )
    except Exception as exc:
        raise ExecutionFingerprintValidationError("input_artifact_public_boundary_invalid") from exc

    validated = dict(input_payload)
    for component_name in REQUIRED_COMPONENT_NAMES:
        component = input_payload[component_name]
        _validate_component(component_name, component)
        if component["run_binding_fingerprint"] != input_payload["run_binding_fingerprint"]:
            raise ExecutionFingerprintValidationError("component_run_binding_mismatch")
        validated[component_name] = dict(component)

    source_binding_fingerprints = {
        validated[name]["source_binding_fingerprint"]
        for name in (
            "source_component",
            "lexical_index_component",
            "graph_ontology_component",
            "answer_component",
            "evaluation_component",
        )
    }
    if len(source_binding_fingerprints) != 1:
        raise ExecutionFingerprintValidationError("component_source_binding_mismatch")

    lexical = validated["lexical_index_component"]
    if {
        lexical["lexical_profile_fingerprint"],
        lexical["query_profile_fingerprint"],
        lexical["evidence_profile_fingerprint"],
    } != {lexical["lexical_profile_fingerprint"]}:
        raise ExecutionFingerprintValidationError("lexical_profile_binding_mismatch")
    if lexical["ascii_fallback_count"] != 0:
        raise ExecutionFingerprintValidationError("ascii_fallback_binding_rejected")

    expected_runtime = current_runtime_binding_fingerprints()
    for field_name in (
        "lexical_profile_fingerprint",
        "dense_profile_fingerprint",
        "runtime_component_fingerprint",
    ):
        if lexical[field_name] != expected_runtime[field_name]:
            raise ExecutionFingerprintValidationError("runtime_component_binding_stale")
    graph = validated["graph_ontology_component"]
    for field_name in (
        "graph_adapter_fingerprint",
        "source_graph_policy_fingerprint",
        "source_identifier_adapter_fingerprint",
        "source_identifier_candidate_schema_fingerprint",
        "source_identifier_extraction_policy_fingerprint",
        "source_identifier_resolution_policy_fingerprint",
        "source_identifier_identity_scope_policy_fingerprint",
        "relation_type_hash_set_fingerprint",
        "ontology_target_fingerprint",
    ):
        if graph[field_name] != expected_runtime[field_name]:
            raise ExecutionFingerprintValidationError("graph_ontology_binding_stale")
    answer = validated["answer_component"]
    for field_name in (
        "answer_model_fingerprint",
        "answer_prompt_fingerprint",
        "answer_budget_fingerprint",
    ):
        if answer[field_name] != expected_runtime[field_name]:
            raise ExecutionFingerprintValidationError("answer_component_binding_stale")
    evaluation = validated["evaluation_component"]
    if evaluation["evaluator_fingerprint"] != expected_runtime["evaluator_fingerprint"]:
        raise ExecutionFingerprintValidationError("evaluator_binding_stale")
    if evaluation["runtime_method_fingerprint"] != expected_runtime["runtime_method_fingerprint"]:
        raise ExecutionFingerprintValidationError("runtime_method_binding_stale")

    expected_code = build_current_code_component(
        repository_root=repository_root,
        run_binding_fingerprint=input_payload["run_binding_fingerprint"],
    )
    if validated["code_component"] != expected_code:
        raise ExecutionFingerprintValidationError("code_tree_attestation_mismatch")

    expected_authority = build_current_authority_component(
        repository_root=repository_root,
        run_binding_fingerprint=input_payload["run_binding_fingerprint"],
    )
    if validated["authority_component"] != expected_authority:
        raise ExecutionFingerprintValidationError("authority_state_stale")

    if canonical_image_id is None or canonical_image_metadata_fingerprint is None:
        raise ExecutionFingerprintValidationError("canonical_image_attestation_missing_or_invalid")
    _require_sha256(
        canonical_image_id,
        "canonical_image_attestation_missing_or_invalid",
    )
    _require_sha256(
        canonical_image_metadata_fingerprint,
        "canonical_image_attestation_missing_or_invalid",
    )
    expected_image = build_image_component(
        run_binding_fingerprint=input_payload["run_binding_fingerprint"],
        image_id=canonical_image_id,
        image_metadata_fingerprint=canonical_image_metadata_fingerprint,
    )
    if validated["image_component"] != expected_image:
        raise ExecutionFingerprintValidationError("canonical_image_attestation_mismatch")
    return validated


def _validate_component(component_name: str, value: Any) -> None:
    if type(value) is not dict or set(value) != _COMPONENT_KEYS[component_name]:
        raise ExecutionFingerprintValidationError("component_schema_invalid")
    if (
        value.get("artifact_id") != _COMPONENT_ARTIFACT_IDS[component_name]
        or value.get("schema_version") != SCHEMA_VERSION
    ):
        raise ExecutionFingerprintValidationError("component_schema_invalid")
    for field_name in _COMPONENT_KEYS[component_name]:
        if field_name.endswith("_fingerprint") or field_name == "image_id":
            _require_sha256(
                value.get(field_name),
                "component_fingerprint_invalid",
            )
    for field_name in _COUNT_FIELDS[component_name]:
        if type(value.get(field_name)) is not int or value[field_name] < 0:
            raise ExecutionFingerprintValidationError("component_count_invalid")
    for field_name in _STATUS_FIELDS[component_name]:
        if value.get(field_name) not in _ALLOWED_STATUSES:
            raise ExecutionFingerprintValidationError("component_status_invalid")
    _validate_artifact_fingerprint(
        value,
        reason_code="component_artifact_fingerprint_invalid",
    )


def _readiness_blockers(payload: Mapping[str, Any]) -> list[str]:
    source = payload["source_component"]
    lexical = payload["lexical_index_component"]
    graph = payload["graph_ontology_component"]
    answer = payload["answer_component"]
    evaluation = payload["evaluation_component"]
    authority = payload["authority_component"]
    blockers: list[str] = []
    if source["status"] != "passed" or source["unexplained_loss_count"] != 0:
        blockers.append("source_completeness_not_passed")
    if evaluation["quality_gate_status"] != "passed":
        blockers.append("uat_quality_gate_not_passed")
    if evaluation["operational_budget_status"] != "passed":
        blockers.append("operational_budget_not_passed")
    if evaluation["independent_holdout_status"] != "passed":
        blockers.append("independent_holdout_not_passed")
    if evaluation["transfer_evaluation_status"] != "passed":
        blockers.append("transfer_evaluation_not_passed")
    if answer["final_answer_acceptance_status"] != "passed":
        blockers.append("final_answer_acceptance_not_passed")
    if lexical["status"] != "passed":
        blockers.append("lexical_index_component_not_passed")
    if graph["status"] != "passed":
        blockers.append("graph_ontology_component_not_passed")
    if answer["status"] != "passed":
        blockers.append("answer_component_not_passed")
    if evaluation["status"] not in {"passed", "blocked"}:
        blockers.append("evaluation_component_not_executable")
    if authority["status"] != "ready" or authority["methodology_ready_status"] != "passed":
        blockers.append("methodology_authority_not_ready")
    if authority["source_completeness_gate_status"] != "passed":
        blockers.append("source_completeness_authority_gate_not_passed")
    if authority["real_source_ablation_gate_status"] != "passed":
        blockers.append("real_source_ablation_authority_gate_not_passed")
    return sorted(set(blockers))


def _validate_bundle(value: Mapping[str, Any]) -> None:
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "run_binding_fingerprint",
        "source_binding_fingerprint",
        "execution_fingerprint",
        "component_artifact_fingerprints",
        "bound_fingerprints",
        "counts",
        "statuses",
        "blocking_status_ids",
        "blocking_status_fingerprint",
        "bundle_fingerprint",
    }
    if (
        type(value) is not dict
        or set(value) != expected_keys
        or value.get("artifact_id") != BUNDLE_ARTIFACT_ID
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") not in {"passed", "blocked"}
    ):
        raise ExecutionFingerprintValidationError("bundle_schema_invalid")
    for field_name in (
        "run_binding_fingerprint",
        "source_binding_fingerprint",
        "execution_fingerprint",
        "blocking_status_fingerprint",
        "bundle_fingerprint",
    ):
        _require_sha256(value.get(field_name), "bundle_fingerprint_invalid")
    component_fingerprints = value.get("component_artifact_fingerprints")
    if (
        type(component_fingerprints) is not dict
        or set(component_fingerprints)
        != {name.removesuffix("_component") for name in REQUIRED_COMPONENT_NAMES}
        or any(not _is_sha256(item) for item in component_fingerprints.values())
    ):
        raise ExecutionFingerprintValidationError("bundle_component_set_invalid")
    bound_fingerprints = value.get("bound_fingerprints")
    if (
        type(bound_fingerprints) is not dict
        or not bound_fingerprints
        or any(not _is_sha256(item) for item in bound_fingerprints.values())
    ):
        raise ExecutionFingerprintValidationError("bundle_binding_set_invalid")
    counts = value.get("counts")
    if (
        type(counts) is not dict
        or not counts
        or any(type(item) is not int or item < 0 for item in counts.values())
    ):
        raise ExecutionFingerprintValidationError("bundle_counts_invalid")
    statuses = value.get("statuses")
    if (
        type(statuses) is not dict
        or not statuses
        or any(item not in _ALLOWED_STATUSES | {"ready"} for item in statuses.values())
    ):
        raise ExecutionFingerprintValidationError("bundle_statuses_invalid")
    blocker_ids = value.get("blocking_status_ids")
    if (
        type(blocker_ids) is not list
        or any(type(item) is not str or not item for item in blocker_ids)
        or blocker_ids != sorted(set(blocker_ids))
        or value["blocking_status_fingerprint"] != sha256_json(blocker_ids)
        or (value["status"] == "passed") != (not blocker_ids)
    ):
        raise ExecutionFingerprintValidationError("bundle_blocking_status_invalid")
    if value["bundle_fingerprint"] != _payload_fingerprint(
        value,
        "bundle_fingerprint",
    ):
        raise ExecutionFingerprintValidationError("bundle_fingerprint_invalid")
    _assert_public_safe(value, "issue56_execution_fingerprint_bundle")


def _validate_public_report(value: Mapping[str, Any]) -> None:
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "acceptance_status",
        "bundle_round_trip_status",
        "public_report_round_trip_status",
        "run_binding_fingerprint",
        "input_artifact_fingerprint",
        "execution_fingerprint",
        "bundle_fingerprint",
        "component_set_fingerprint",
        "component_count",
        "accepted_component_count",
        "blocked_component_count",
        "blocking_status_ids",
        "blocking_status_fingerprint",
        "authority_state_fingerprint",
        "authority_execution_fingerprint",
        "uat_report_fingerprint",
        "uat_run_fingerprint",
        "source_item_count",
        "observation_count",
        "index_count",
        "graph_node_count",
        "graph_edge_count",
        "selected_identifier_mention_count",
        "authorized_identifier_mention_count",
        "selected_resolved_identifier_candidate_count",
        "evaluated_case_count",
        "report_fingerprint",
    }
    if (
        type(value) is not dict
        or set(value) != expected_keys
        or value.get("artifact_id") != REPORT_ARTIFACT_ID
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") not in {"passed", "blocked"}
        or value.get("acceptance_status") != value.get("status")
        or value.get("bundle_round_trip_status") != "passed"
        or value.get("public_report_round_trip_status") != "passed"
    ):
        raise ExecutionFingerprintValidationError("public_report_schema_invalid")
    for field_name, field_value in value.items():
        if field_name.endswith("_fingerprint"):
            _require_sha256(field_value, "public_report_fingerprint_invalid")
        elif field_name.endswith("_count"):
            if type(field_value) is not int or field_value < 0:
                raise ExecutionFingerprintValidationError("public_report_count_invalid")
        elif field_name.endswith("_status"):
            if field_value not in {"passed", "blocked"}:
                raise ExecutionFingerprintValidationError("public_report_status_invalid")
    blocker_ids = value.get("blocking_status_ids")
    if (
        type(blocker_ids) is not list
        or blocker_ids != sorted(set(blocker_ids))
        or any(type(item) is not str or not item for item in blocker_ids)
        or value["blocking_status_fingerprint"] != sha256_json(blocker_ids)
    ):
        raise ExecutionFingerprintValidationError("public_report_blockers_invalid")
    if value["report_fingerprint"] != _payload_fingerprint(
        value,
        "report_fingerprint",
    ):
        raise ExecutionFingerprintValidationError("public_report_fingerprint_invalid")
    _assert_public_safe(value, "issue56_execution_fingerprint_public_report")


def _scoped_code_tree_fingerprint(repository_root: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    file_count = 0
    candidates: list[Path] = []
    for relative_directory in _CODE_DIRECTORY_SCOPES:
        directory = repository_root / relative_directory
        if not directory.is_dir() or directory.is_symlink():
            raise ExecutionFingerprintValidationError("code_tree_attestation_unavailable")
        for candidate in directory.rglob("*"):
            if "__pycache__" in candidate.parts or candidate.suffix in {".pyc", ".pyo"}:
                continue
            metadata = candidate.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ExecutionFingerprintValidationError("code_tree_attestation_symlink_rejected")
            if stat.S_ISREG(metadata.st_mode):
                candidates.append(candidate)
            elif not stat.S_ISDIR(metadata.st_mode):
                raise ExecutionFingerprintValidationError(
                    "code_tree_attestation_nonregular_rejected"
                )
    for relative_file in _CODE_FILE_SCOPES:
        candidates.append(repository_root / relative_file)
    for candidate in sorted(
        candidates,
        key=lambda item: item.relative_to(repository_root).as_posix(),
    ):
        metadata = candidate.lstat()
        if not stat.S_ISREG(metadata.st_mode) or candidate.is_symlink():
            raise ExecutionFingerprintValidationError("code_tree_attestation_unavailable")
        relative = candidate.relative_to(repository_root).as_posix().encode("utf-8")
        content_hash = _regular_file_sha256(
            candidate,
            resolved_root=repository_root,
        )
        digest.update(relative)
        digest.update(b"\0")
        digest.update(f"{stat.S_IMODE(metadata.st_mode):04o}".encode("ascii"))
        digest.update(b"\0")
        digest.update(content_hash.encode("ascii"))
        digest.update(b"\0")
        file_count += 1
    return f"sha256:{digest.hexdigest()}", file_count


def _regular_file_sha256(path: Path, *, resolved_root: Path) -> str:
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(resolved_root)
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        content = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise ExecutionFingerprintValidationError("code_tree_attestation_unavailable") from exc
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _resolved_repository_root(repository_root: Path) -> Path:
    try:
        resolved = repository_root.resolve(strict=True)
    except OSError as exc:
        raise ExecutionFingerprintValidationError("code_revision_attestation_unavailable") from exc
    if not resolved.is_dir() or resolved.is_symlink():
        raise ExecutionFingerprintValidationError("code_revision_attestation_unavailable")
    return resolved


def _git_output(repository_root: Path, arguments: Sequence[str]) -> str:
    return _git_output_bytes(repository_root, arguments).decode("utf-8").strip()


def _git_output_bytes(repository_root: Path, arguments: Sequence[str]) -> bytes:
    try:
        result = subprocess.run(
            (
                "git",
                "-c",
                f"safe.directory={repository_root}",
                "-C",
                str(repository_root),
                *arguments,
            ),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExecutionFingerprintValidationError("code_revision_attestation_unavailable") from exc
    return result.stdout


def _persist_immutable_json(
    path: Path,
    payload: Mapping[str, Any],
    *,
    validator: Any,
) -> dict[str, Any]:
    serialized = _canonical_json_bytes(payload) + b"\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != serialized:
                raise ExecutionFingerprintValidationError("immutable_output_conflict")
        else:
            descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            try:
                os.write(descriptor, serialized)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        loaded = _read_json_object(path)
    except ExecutionFingerprintValidationError:
        raise
    except OSError as exc:
        raise ExecutionFingerprintValidationError("artifact_persistence_failed") from exc
    validator(loaded)
    return loaded


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if metadata.st_size > _MAX_INPUT_BYTES:
            raise OSError
        payload = path.read_bytes()
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
    except ExecutionFingerprintValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExecutionFingerprintValidationError("json_artifact_unavailable_or_invalid") from exc
    if type(value) is not dict:
        raise ExecutionFingerprintValidationError("json_artifact_unavailable_or_invalid")
    return value


def _read_json_object_with_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    reason_code: str,
) -> tuple[bytes, dict[str, Any]]:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum_bytes:
            raise OSError
        payload = b""
        while len(payload) <= maximum_bytes:
            chunk = os.read(descriptor, min(64 * 1024, maximum_bytes + 1 - len(payload)))
            if not chunk:
                break
            payload += chunk
        if len(payload) > maximum_bytes:
            raise OSError
        value = json.loads(payload, object_pairs_hook=_unique_json_object)
    except ExecutionFingerprintValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExecutionFingerprintValidationError(reason_code) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if type(value) is not dict:
        raise ExecutionFingerprintValidationError(reason_code)
    return payload, value


def _unique_json_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ExecutionFingerprintValidationError("json_duplicate_key_rejected")
        value[key] = item
    return value


def _validate_artifact_fingerprint(
    value: Mapping[str, Any],
    *,
    reason_code: str,
) -> None:
    _require_sha256(value.get(_HASH_FIELD), reason_code)
    if value[_HASH_FIELD] != _payload_fingerprint(value, _HASH_FIELD):
        raise ExecutionFingerprintValidationError(reason_code)


def _payload_fingerprint(value: Mapping[str, Any], fingerprint_field: str) -> str:
    return sha256_json({key: item for key, item in value.items() if key != fingerprint_field})


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _is_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == _HASH_LENGTH
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _require_sha256(value: Any, reason_code: str) -> None:
    if not _is_sha256(value):
        raise ExecutionFingerprintValidationError(reason_code)


def _assert_public_safe(value: Any, context: str) -> None:
    try:
        assert_no_public_raw_references(value, context)
    except Exception as exc:
        raise ExecutionFingerprintValidationError(
            "public_projection_contains_unsafe_reference"
        ) from exc


def _assert_completed_uat_public_safe(report: Mapping[str, Any]) -> None:
    projection = json.loads(json.dumps(report, ensure_ascii=True, sort_keys=True))
    resource_measurement = projection.get("resource_measurement")
    if isinstance(resource_measurement, dict):
        usage = resource_measurement.get("model_usage_cost")
        if isinstance(usage, dict):
            if "input_token_count" in usage:
                usage["input_usage_count"] = usage.pop("input_token_count")
            if "output_token_count" in usage:
                usage["output_usage_count"] = usage.pop("output_token_count")
    _assert_public_safe(projection, "issue56_completed_uat_report")


def _rejection_report(reason_code: str) -> dict[str, Any]:
    report = {
        "artifact_id": ERROR_ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "rejected",
        "rejection_status_id": reason_code,
        "rejection_count": 1,
    }
    _assert_public_safe(report, "issue56_execution_fingerprint_rejection")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    parser.add_argument("--uat-report", type=Path)
    parser.add_argument("--expected-uat-report-fingerprint")
    parser.add_argument(
        "--canonical-image-id",
        default=os.environ.get("FORMOWL_CANONICAL_IMAGE_ID"),
    )
    parser.add_argument(
        "--canonical-image-metadata-fingerprint",
        default=os.environ.get("FORMOWL_CANONICAL_IMAGE_METADATA_FINGERPRINT"),
    )
    args = parser.parse_args(argv)

    try:
        if args.uat_report is None:
            raise ExecutionFingerprintValidationError("uat_report_missing_or_invalid")
        if args.expected_uat_report_fingerprint is None:
            raise ExecutionFingerprintValidationError(
                "expected_uat_report_fingerprint_missing_or_invalid"
            )
        input_payload = _read_json_object(args.input)
        artifacts = create_execution_fingerprint_artifacts(
            input_payload=input_payload,
            uat_report_path=args.uat_report,
            expected_uat_report_fingerprint=args.expected_uat_report_fingerprint,
            repository_root=ROOT,
            canonical_image_id=args.canonical_image_id,
            canonical_image_metadata_fingerprint=(args.canonical_image_metadata_fingerprint),
        )
        persisted = persist_execution_fingerprint_artifacts(
            artifacts=artifacts,
            bundle_output=args.output,
            public_output=args.public_output,
        )
        print(
            json.dumps(
                persisted.public_report,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if persisted.public_report["status"] == "passed" else 2
    except ExecutionFingerprintValidationError as exc:
        print(
            json.dumps(
                _rejection_report(exc.reason_code),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 3
    except Exception:
        print(
            json.dumps(
                _rejection_report("unexpected_validation_failure"),
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
