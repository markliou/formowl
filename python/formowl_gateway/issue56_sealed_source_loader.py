"""Environment-bound adapter for the Issue #56 sealed-source diagnostic.

The CLI resolves this module by ``module:function``.  Source loading remains in
``formowl_mail.issue56_sealed_source`` so the mail owner path never imports the
gateway contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
from typing import Any, Final

from formowl_contract import ContractValidationError, sha256_json
from formowl_mail.answer import render_governed_evidence_answer
from formowl_mail.issue56_sealed_source import (
    APPROVER_ACTOR,
    ARTIFACT_ID as SEALED_SOURCE_LOAD_ARTIFACT_ID,
    IDENTITY_SCOPE_MODE,
    SOURCE_GRAPH_POLICY_ID,
    WORKSPACE_ID,
    load_issue56_sealed_source,
)

from .issue56_diagnostic import (
    ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_ID,
    ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
    ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID,
    ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID,
    Issue56SealedSourceDiagnosticInput,
    build_issue56_sealed_source_diagnostic_input,
)
from .semantic import validate_public_gateway_payload


LOADER_SPEC: Final[str] = (
    "formowl_gateway.issue56_sealed_source_loader:" "load_issue56_sealed_source_diagnostic_input"
)
REAL_PROMPT_LOADER_SPEC: Final[str] = (
    "formowl_gateway.issue56_sealed_source_loader:"
    "load_issue56_real_prompt_sealed_source_diagnostic_input"
)
RELATION_PROJECTION_EQUIVALENCE_LOADER_SPEC: Final[str] = (
    "formowl_gateway.issue56_sealed_source_loader:"
    "load_issue56_relation_projection_equivalence_diagnostic_input"
)
RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_SPEC: Final[str] = (
    "formowl_gateway.issue56_sealed_source_loader:"
    "load_issue56_relation_projection_equivalence_v6_diagnostic_input"
)
RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_SPEC: Final[str] = (
    "formowl_gateway.issue56_sealed_source_loader:"
    "load_issue56_relation_projection_offline_equivalence_v7_diagnostic_input"
)
LOADER_CONTRACT_FINGERPRINT: Final[str] = sha256_json(
    {
        "loader_contract_id": ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID,
        "sealed_source_load_artifact_id": SEALED_SOURCE_LOAD_ARTIFACT_ID,
        "identity_scope_mode": IDENTITY_SCOPE_MODE,
        "workspace_id": WORKSPACE_ID,
        "approver_actor": APPROVER_ACTOR,
        "source_graph_policy_id": SOURCE_GRAPH_POLICY_ID,
        "lineage_crosswalk_precompute_contract_id": (
            "formowl_issue56_lineage_crosswalk_precompute_safe_v1"
        ),
        "lineage_crosswalk_precompute_invocation_owner": ("formowl_mail.issue56_sealed_source"),
        "relation_projection_base_precompute_contract_id": (
            "formowl_issue56_relation_projection_base_precompute_v1"
        ),
        "relation_projection_base_precompute_invocation_owner": (
            "formowl_mail.issue56_sealed_source"
        ),
        "source_input_mode": "explicit_environment_paths_and_byte_seals_v1",
        "tenant_id_allowed": False,
        "uat_or_holdout_manifest_input_allowed": False,
        "canonical_write_allowed": False,
    }
)
REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT: Final[str] = sha256_json(
    {
        "loader_contract_id": (ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID),
        "base_loader_contract_fingerprint": LOADER_CONTRACT_FINGERPRINT,
        "selector_symbol": (
            "formowl_mail.issue56_real_prompt:" "select_source_backed_connected_identifier_prompt"
        ),
        "selector_invocation_count": 1,
        "selector_input": "Issue56SealedSourceLoad",
        "selector_output": ("private_prompt_plus_hash_count_only_safe_selection_proof_v1"),
        "identity_scope_mode": IDENTITY_SCOPE_MODE,
        "workspace_id": WORKSPACE_ID,
        "approver_actor": APPROVER_ACTOR,
        "tenant_id_allowed": False,
        "uat_or_holdout_manifest_input_allowed": False,
        "canonical_write_allowed": False,
    }
)
RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_FINGERPRINT: Final[str] = sha256_json(
    {
        "loader_contract_id": (ISSUE56_RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_ID),
        "base_real_prompt_loader_contract_fingerprint": (REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT),
        "source_view_policy": ("one_owner_precomputed_view_plus_gateway_isolated_cold_copy_v1"),
        "relation_projection_base_precompute_invocation_count": 1,
        "relation_projection_base_precompute_invocation_owner": (
            "formowl_mail.issue56_sealed_source"
        ),
        "identity_scope_mode": IDENTITY_SCOPE_MODE,
        "workspace_id": WORKSPACE_ID,
        "approver_actor": APPROVER_ACTOR,
        "tenant_id_allowed": False,
        "uat_or_holdout_manifest_input_allowed": False,
        "canonical_write_allowed": False,
    }
)
RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_FINGERPRINT: Final[str] = sha256_json(
    {
        "loader_contract_id": (ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_ID),
        "base_real_prompt_loader_contract_fingerprint": (REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT),
        "source_view_policy": (
            "one_owner_precomputed_view_plus_gateway_public_snapshot_only_"
            "presealed_isolated_cold_copy_v2"
        ),
        "graph_content_snapshot_precompute_contract_id": (
            "formowl_issue56_effective_graph_content_snapshot_precompute_v1"
        ),
        "graph_content_snapshot_precompute_symbol": (
            "formowl_mail:precompute_effective_graph_content_snapshot"
        ),
        "graph_content_snapshot_precompute_invocation_count": 1,
        "graph_content_snapshot_precompute_invocation_owner": (
            "formowl_gateway.issue56_diagnostic"
        ),
        "graph_content_snapshot_relation_cache_policy": "binding_0_base_0",
        "relation_projection_base_precompute_invocation_count": 1,
        "relation_projection_base_precompute_invocation_owner": (
            "formowl_mail.issue56_sealed_source"
        ),
        "gateway_relation_projection_base_precompute_allowed": False,
        "identity_scope_mode": IDENTITY_SCOPE_MODE,
        "workspace_id": WORKSPACE_ID,
        "approver_actor": APPROVER_ACTOR,
        "tenant_id_allowed": False,
        "uat_or_holdout_manifest_input_allowed": False,
        "canonical_write_allowed": False,
    }
)
RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_FINGERPRINT: Final[str] = sha256_json(
    {
        "loader_contract_id": (
            ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID
        ),
        "base_real_prompt_loader_contract_fingerprint": (REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT),
        "source_view_policy": (
            "two_gateway_fresh_public_snapshot_only_presealed_cold_views_"
            "then_after_owner_relation_precompute_before_claim_v1"
        ),
        "graph_content_snapshot_precompute_contract_id": (
            "formowl_issue56_effective_graph_content_snapshot_precompute_v1"
        ),
        "graph_content_snapshot_precompute_symbol": (
            "formowl_mail:precompute_effective_graph_content_snapshot"
        ),
        "graph_content_snapshot_precompute_invocation_count": 2,
        "preclaim_after_relation_projection_base_precompute_symbol": (
            "formowl_mail.hybrid:precompute_relation_projection_base"
        ),
        "preclaim_after_relation_projection_base_precompute_invocation_count": 1,
        "postclaim_cold_relation_projection_diagnostic_symbol": (
            "formowl_mail:precompute_relation_projection_base_cold_diagnostic"
        ),
        "postclaim_cold_relation_projection_diagnostic_invocation_count": 1,
        "user_query_time_budget_ms": 1500,
        "phase_local_query_budget_override_allowed": False,
        "identity_scope_mode": IDENTITY_SCOPE_MODE,
        "workspace_id": WORKSPACE_ID,
        "approver_actor": APPROVER_ACTOR,
        "tenant_id_allowed": False,
        "uat_or_holdout_manifest_input_allowed": False,
        "canonical_write_allowed": False,
    }
)

_ENVIRONMENT_FIELDS: Final[dict[str, str]] = {
    "retrieval_snapshot_path": "FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_PATH",
    "expected_retrieval_snapshot_sha256": ("FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_SHA256"),
    "bundle_artifact_path": "FORMOWL_ISSUE56_BUNDLE_ARTIFACT_PATH",
    "expected_bundle_artifact_sha256": ("FORMOWL_ISSUE56_BUNDLE_ARTIFACT_SHA256"),
    "retrieval_report_path": "FORMOWL_ISSUE56_RETRIEVAL_REPORT_PATH",
    "expected_retrieval_report_sha256": ("FORMOWL_ISSUE56_RETRIEVAL_REPORT_SHA256"),
    "materialized_work_dir": "FORMOWL_ISSUE56_MATERIALIZED_WORK_DIR",
    "expected_materialization_artifact_sha256": ("FORMOWL_ISSUE56_MATERIALIZATION_ARTIFACT_SHA256"),
    "expected_materialization_safe_report_sha256": (
        "FORMOWL_ISSUE56_MATERIALIZATION_SAFE_REPORT_SHA256"
    ),
    "identity_scope_attestation_path": ("FORMOWL_ISSUE56_IDENTITY_SCOPE_ATTESTATION_PATH"),
    "expected_identity_scope_attestation_sha256": (
        "FORMOWL_ISSUE56_IDENTITY_SCOPE_ATTESTATION_SHA256"
    ),
    "identity_scope_safe_report_path": ("FORMOWL_ISSUE56_IDENTITY_SCOPE_SAFE_REPORT_PATH"),
    "expected_identity_scope_safe_report_sha256": (
        "FORMOWL_ISSUE56_IDENTITY_SCOPE_SAFE_REPORT_SHA256"
    ),
    "source_identifier_candidate_artifact_path": (
        "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_PATH"
    ),
    "expected_source_identifier_candidate_artifact_sha256": (
        "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_ARTIFACT_SHA256"
    ),
    "source_identifier_candidate_safe_report_path": (
        "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_SAFE_REPORT_PATH"
    ),
    "expected_source_identifier_candidate_safe_report_sha256": (
        "FORMOWL_ISSUE56_SOURCE_IDENTIFIER_CANDIDATE_SAFE_REPORT_SHA256"
    ),
    "expected_identity_scope_fingerprint": ("FORMOWL_ISSUE56_IDENTITY_SCOPE_FINGERPRINT"),
}
_PATH_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "retrieval_snapshot_path",
        "bundle_artifact_path",
        "retrieval_report_path",
        "materialized_work_dir",
        "identity_scope_attestation_path",
        "identity_scope_safe_report_path",
        "source_identifier_candidate_artifact_path",
        "source_identifier_candidate_safe_report_path",
    }
)


def load_issue56_sealed_source_diagnostic_input() -> Issue56SealedSourceDiagnosticInput:
    """Zero-argument CLI loader for one explicitly sealed source package."""

    loaded = _load_approved_sealed_source()
    return _build_gateway_input(
        loaded,
        loader_contract_fingerprint=LOADER_CONTRACT_FINGERPRINT,
    )


def load_issue56_real_prompt_sealed_source_diagnostic_input(
    *,
    selector: Callable[[Any], Any] | None = None,
) -> Issue56SealedSourceDiagnosticInput:
    """Load, verify, and select one private source-backed prompt for v4.

    The owner helper is imported only after the sealed package has passed its
    owner loader.  Its prompt remains private; only its sealed hash/count proof
    crosses into the gateway diagnostic contract.
    """

    loaded = _load_approved_sealed_source()
    if selector is None:
        from formowl_mail.issue56_real_prompt import (
            select_source_backed_connected_identifier_prompt,
        )

        selector = select_source_backed_connected_identifier_prompt
    relation_types = tuple(
        sorted({edge.relation_type for edge in loaded.effective_graph_view.visible_edges})
    )
    selected = selector(
        session=loaded.session,
        effective_graph_view=loaded.effective_graph_view,
        candidate_inventory=loaded.identifier_mention_batch,
        allowed_relation_types=relation_types,
    )
    private_prompt, owner_selection_proof = _normalize_prompt_selection(selected)
    safe_binding = _validated_owner_safe_binding(loaded.safe_binding)
    safe_selection_proof = _gateway_prompt_selection_binding(
        private_prompt=private_prompt,
        owner_selection_proof=owner_selection_proof,
        source_loader_binding_fingerprint=str(safe_binding["binding_fingerprint"]),
        permission_fingerprint=str(safe_binding["permission_fingerprint"]),
    )
    return _build_gateway_input(
        loaded,
        loader_contract_fingerprint=(REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT),
        diagnostic_mode_id=(ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID),
        private_prompt=private_prompt,
        prompt_selection=safe_selection_proof,
    )


def load_issue56_relation_projection_equivalence_diagnostic_input(
    *,
    selector: Callable[[Any], Any] | None = None,
) -> Issue56SealedSourceDiagnosticInput:
    """Load one owner-precomputed source for the paired v5 diagnostic."""

    loaded = _load_approved_sealed_source()
    if selector is None:
        from formowl_mail.issue56_real_prompt import (
            select_source_backed_connected_identifier_prompt,
        )

        selector = select_source_backed_connected_identifier_prompt
    relation_types = tuple(
        sorted({edge.relation_type for edge in loaded.effective_graph_view.visible_edges})
    )
    selected = selector(
        session=loaded.session,
        effective_graph_view=loaded.effective_graph_view,
        candidate_inventory=loaded.identifier_mention_batch,
        allowed_relation_types=relation_types,
    )
    private_prompt, owner_selection_proof = _normalize_prompt_selection(selected)
    safe_binding = _validated_owner_safe_binding(loaded.safe_binding)
    safe_selection_proof = _gateway_prompt_selection_binding(
        private_prompt=private_prompt,
        owner_selection_proof=owner_selection_proof,
        source_loader_binding_fingerprint=str(safe_binding["binding_fingerprint"]),
        permission_fingerprint=str(safe_binding["permission_fingerprint"]),
    )
    return _build_gateway_input(
        loaded,
        loader_contract_fingerprint=(RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_FINGERPRINT),
        diagnostic_mode_id=(ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID),
        private_prompt=private_prompt,
        prompt_selection=safe_selection_proof,
    )


def load_issue56_relation_projection_equivalence_v6_diagnostic_input(
    *,
    selector: Callable[[Any], Any] | None = None,
) -> Issue56SealedSourceDiagnosticInput:
    """Load one owner-precomputed source for the paired v6 diagnostic."""

    loaded = _load_approved_sealed_source()
    if selector is None:
        from formowl_mail.issue56_real_prompt import (
            select_source_backed_connected_identifier_prompt,
        )

        selector = select_source_backed_connected_identifier_prompt
    relation_types = tuple(
        sorted({edge.relation_type for edge in loaded.effective_graph_view.visible_edges})
    )
    selected = selector(
        session=loaded.session,
        effective_graph_view=loaded.effective_graph_view,
        candidate_inventory=loaded.identifier_mention_batch,
        allowed_relation_types=relation_types,
    )
    private_prompt, owner_selection_proof = _normalize_prompt_selection(selected)
    safe_binding = _validated_owner_safe_binding(loaded.safe_binding)
    safe_selection_proof = _gateway_prompt_selection_binding(
        private_prompt=private_prompt,
        owner_selection_proof=owner_selection_proof,
        source_loader_binding_fingerprint=str(safe_binding["binding_fingerprint"]),
        permission_fingerprint=str(safe_binding["permission_fingerprint"]),
    )
    return _build_gateway_input(
        loaded,
        loader_contract_fingerprint=(
            RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_FINGERPRINT
        ),
        diagnostic_mode_id=(ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID),
        private_prompt=private_prompt,
        prompt_selection=safe_selection_proof,
    )


def load_issue56_relation_projection_offline_equivalence_v7_diagnostic_input(
    *,
    selector: Callable[[Any], Any] | None = None,
) -> Issue56SealedSourceDiagnosticInput:
    """Load one sealed source for the post-claim offline v7 comparison."""

    loaded = _load_approved_sealed_source()
    if selector is None:
        from formowl_mail.issue56_real_prompt import (
            select_source_backed_connected_identifier_prompt,
        )

        selector = select_source_backed_connected_identifier_prompt
    relation_types = tuple(
        sorted({edge.relation_type for edge in loaded.effective_graph_view.visible_edges})
    )
    selected = selector(
        session=loaded.session,
        effective_graph_view=loaded.effective_graph_view,
        candidate_inventory=loaded.identifier_mention_batch,
        allowed_relation_types=relation_types,
    )
    private_prompt, owner_selection_proof = _normalize_prompt_selection(selected)
    safe_binding = _validated_owner_safe_binding(loaded.safe_binding)
    safe_selection_proof = _gateway_prompt_selection_binding(
        private_prompt=private_prompt,
        owner_selection_proof=owner_selection_proof,
        source_loader_binding_fingerprint=str(safe_binding["binding_fingerprint"]),
        permission_fingerprint=str(safe_binding["permission_fingerprint"]),
    )
    return _build_gateway_input(
        loaded,
        loader_contract_fingerprint=(
            RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_FINGERPRINT
        ),
        diagnostic_mode_id=(ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID),
        private_prompt=private_prompt,
        prompt_selection=safe_selection_proof,
    )


def _load_approved_sealed_source() -> Any:
    values: dict[str, str | Path] = {}
    for field_name, environment_name in _ENVIRONMENT_FIELDS.items():
        value = os.environ.get(environment_name)
        if value is None or not value.strip():
            raise ContractValidationError(
                f"sealed source loader environment is incomplete: {environment_name}"
            )
        values[field_name] = Path(value) if field_name in _PATH_FIELDS else value

    return load_issue56_sealed_source(
        **values,
        identity_scope_mode=IDENTITY_SCOPE_MODE,
        workspace_id=WORKSPACE_ID,
        approver_actor=APPROVER_ACTOR,
        requester_user_id=APPROVER_ACTOR,
    )


def build_issue56_production_semantic_retrieval_handler() -> Callable[..., dict[str, Any]]:
    """Build the opt-in production handler over the approved sealed source."""

    loaded = _load_approved_sealed_source()
    _validated_owner_safe_binding(loaded.safe_binding)
    session, graph_view = loaded.session, loaded.effective_graph_view
    relation_types = tuple(sorted({edge.relation_type for edge in graph_view.visible_edges}))
    relation_by_edge_hash: dict[str, str] = {}
    for edge in graph_view.visible_edges:
        edge_hash = sha256_json(edge.edge_id)
        if edge_hash in relation_by_edge_hash:
            raise ContractValidationError("production graph edge binding is ambiguous")
        relation_by_edge_hash[edge_hash] = edge.relation_type
    if (
        session.requester_user_id != APPROVER_ACTOR
        or session.workspace_id != WORKSPACE_ID
        or graph_view.requester_user_id != APPROVER_ACTOR
        or not relation_types
    ):
        raise ContractValidationError("production sealed source binding is invalid")

    def retrieval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
        if set(arguments) != {
            "query_text",
            "requester_user_id",
            "session_id",
            "workspace_id",
        }:
            raise ContractValidationError("production semantic arguments are invalid")
        if (
            arguments["requester_user_id"] != session.requester_user_id
            or arguments["workspace_id"] != session.workspace_id
            or not isinstance(arguments["session_id"], str)
            or not arguments["session_id"]
        ):
            raise ContractValidationError("production semantic actor binding mismatch")
        result = session.query(
            query_text=arguments["query_text"],
            effective_graph_view=graph_view,
            allowed_relation_types=relation_types,
        )
        answer = render_governed_evidence_answer(result)
        if result.graph_path_count != len(result.graph_paths):
            raise ContractValidationError("production graph path count is inconsistent")
        projected_relation_types: set[str] = set()
        for path in result.graph_paths:
            if path.hop_count != len(path.hops):
                raise ContractValidationError("production graph path binding is inconsistent")
            for hop in path.hops:
                relation_type = relation_by_edge_hash.get(hop.edge_hash)
                if relation_type is None or sha256_json(relation_type) != hop.relation_type_hash:
                    raise ContractValidationError("production graph relation binding is invalid")
                projected_relation_types.add(relation_type)
        payload = {
            "status": result.status,
            "answer": {
                "status": answer.status,
                "text": answer.answer_text,
                "answer_hash": answer.answer_hash,
                "citation_count": len(answer.citation_hashes),
            },
            "citations": list(answer.citation_hashes),
            "graph_hits": {"count": result.graph_path_count},
            "relationship": {
                "relation_types": sorted(projected_relation_types),
                "path_count": len(result.graph_paths),
                "max_hops": max((path.hop_count for path in result.graph_paths), default=0),
            },
            "redaction_counts": {"redacted_value_count": 0},
        }
        validate_public_gateway_payload(payload)
        return payload

    return retrieval_handler


def _build_gateway_input(
    loaded: Any,
    *,
    loader_contract_fingerprint: str,
    diagnostic_mode_id: str | None = None,
    private_prompt: str | None = None,
    prompt_selection: Mapping[str, Any] | None = None,
) -> Issue56SealedSourceDiagnosticInput:
    relation_types = tuple(
        sorted({edge.relation_type for edge in loaded.effective_graph_view.visible_edges})
    )
    if not relation_types:
        raise ContractValidationError("sealed source graph has no authorized relation types")
    safe_binding = _validated_owner_safe_binding(loaded.safe_binding)
    return build_issue56_sealed_source_diagnostic_input(
        session=loaded.session,
        effective_graph_view=loaded.effective_graph_view,
        allowed_relation_types=relation_types,
        source_asset_fingerprint=str(safe_binding["source_asset_fingerprint"]),
        loader_contract_fingerprint=loader_contract_fingerprint,
        graph_revision_fingerprint=str(safe_binding["graph_revision_fingerprint"]),
        source_loader_binding_fingerprint=str(safe_binding["binding_fingerprint"]),
        lineage_crosswalk_precompute=safe_binding["lineage_crosswalk_precompute"],
        relation_projection_base_precompute=safe_binding["relation_projection_base_precompute"],
        private_prompt=private_prompt,
        prompt_selection=prompt_selection,
        **({"diagnostic_mode_id": diagnostic_mode_id} if diagnostic_mode_id is not None else {}),
    )


def _normalize_prompt_selection(
    selected: Any,
) -> tuple[str, Mapping[str, Any]]:
    if isinstance(selected, Mapping):
        prompt = selected.get("runtime_prompt")
        proof = selected.get("safe_selection_proof")
    else:
        prompt = getattr(selected, "runtime_prompt", None)
        proof = getattr(selected, "safe_selection_proof", None)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ContractValidationError(
            "source-backed connected prompt selector returned no private prompt"
        )
    if not isinstance(proof, Mapping):
        raise ContractValidationError(
            "source-backed connected prompt selector returned no safe proof"
        )
    return prompt, dict(proof)


def _gateway_prompt_selection_binding(
    *,
    private_prompt: str,
    owner_selection_proof: Mapping[str, Any],
    source_loader_binding_fingerprint: str,
    permission_fingerprint: str,
) -> dict[str, Any]:
    selected_term_hashes = owner_selection_proof.get("selected_term_hashes")
    selected_identifier_count = owner_selection_proof.get("selected_identifier_count")
    path_observation_count = owner_selection_proof.get("path_observation_count")
    if (
        not isinstance(selected_term_hashes, list)
        or type(selected_identifier_count) is not int
        or type(path_observation_count) is not int
    ):
        raise ContractValidationError("source-backed connected prompt owner proof is incomplete")
    binding: dict[str, Any] = {
        "artifact_id": "formowl_issue56_real_prompt_gateway_selection_binding_v1",
        "schema_version": 1,
        "status": "passed",
        "prompt_hash": sha256_json(private_prompt),
        "source_loader_binding_fingerprint": (source_loader_binding_fingerprint),
        "permission_fingerprint": permission_fingerprint,
        "owner_selection_proof": dict(owner_selection_proof),
        "counts": {
            "lexical_anchor_count": len(selected_term_hashes),
            "selected_identifier_count": selected_identifier_count,
            "authorized_connected_graph_path_count": 1,
            "supporting_observation_count": path_observation_count,
        },
    }
    binding["selection_proof_fingerprint"] = sha256_json(binding)
    return binding


def _validated_owner_safe_binding(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ContractValidationError("sealed source owner safe binding is invalid")
    binding = dict(raw)
    binding_fingerprint = binding.get("binding_fingerprint")
    if not isinstance(binding_fingerprint, str):
        raise ContractValidationError("sealed source owner safe binding is incomplete")
    fingerprint_payload = dict(binding)
    fingerprint_payload.pop("binding_fingerprint", None)
    if sha256_json(fingerprint_payload) != binding_fingerprint:
        raise ContractValidationError("sealed source owner safe binding seal mismatch")
    precompute = binding.get("lineage_crosswalk_precompute")
    relation_precompute = binding.get("relation_projection_base_precompute")
    counts = binding.get("counts")
    if (
        binding.get("status") != "passed"
        or binding.get("identity_scope_mode_status") != IDENTITY_SCOPE_MODE
        or binding.get("tenant_dimension_status") != "not_modeled_not_fabricated"
        or not isinstance(precompute, Mapping)
        or not isinstance(counts, Mapping)
        or precompute.get("index_fingerprint") != binding.get("index_fingerprint")
        or precompute.get("graph_revision_fingerprint") != binding.get("graph_revision_fingerprint")
        or not isinstance(precompute.get("counts"), Mapping)
        or precompute["counts"].get("authorized_evidence_count")
        != counts.get("authorized_observation_count")
    ):
        raise ContractValidationError("sealed source owner precompute binding mismatch")
    relation_counts = (
        relation_precompute.get("counts") if isinstance(relation_precompute, Mapping) else None
    )
    required_relation_count_fields = {
        "authorized_observation_count",
        "candidate_count",
        "projected_node_count",
        "observation_bound_node_group_count",
        "adjacency_node_count",
        "adjacency_transition_count",
        "authorized_index_vocabulary_hash_count",
        "authorized_graph_vocabulary_hash_count",
    }
    outer_graph_counts = (
        counts.get("graph_observation_node_count"),
        counts.get("graph_entity_node_count"),
        counts.get("graph_edge_count"),
    )
    if (
        not isinstance(relation_precompute, Mapping)
        or relation_precompute.get("artifact_id")
        != "formowl_issue56_relation_projection_base_precompute_v1"
        or relation_precompute.get("schema_version") != 1
        or relation_precompute.get("status") != "passed"
        or relation_precompute.get("cache_status") != "primed"
        or relation_precompute.get("helper_invocation_count") != 1
        or isinstance(relation_precompute.get("elapsed_ms"), bool)
        or not isinstance(relation_precompute.get("elapsed_ms"), (int, float))
        or relation_precompute["elapsed_ms"] < 0
        or not isinstance(relation_counts, Mapping)
        or set(relation_counts) != required_relation_count_fields
        or any(type(value) is not int or value < 0 for value in relation_counts.values())
        or any(type(value) is not int or value < 0 for value in outer_graph_counts)
        or relation_precompute.get("index_fingerprint") != binding.get("index_fingerprint")
        or relation_precompute.get("graph_revision_fingerprint")
        != binding.get("graph_revision_fingerprint")
        or relation_precompute.get("candidate_admission_profile_fingerprint")
        != binding.get("candidate_admission_profile_fingerprint")
        or relation_counts.get("authorized_observation_count")
        != counts.get("authorized_observation_count")
        or relation_counts.get("projected_node_count")
        != outer_graph_counts[0] + outer_graph_counts[1]
        or relation_counts.get("adjacency_transition_count") != 2 * outer_graph_counts[2]
        or relation_counts["adjacency_node_count"] > relation_counts["projected_node_count"]
    ):
        raise ContractValidationError(
            "sealed source owner relation projection precompute binding mismatch"
        )
    return binding


__all__ = [
    "LOADER_CONTRACT_FINGERPRINT",
    "LOADER_SPEC",
    "REAL_PROMPT_LOADER_CONTRACT_FINGERPRINT",
    "REAL_PROMPT_LOADER_SPEC",
    "RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_FINGERPRINT",
    "RELATION_PROJECTION_EQUIVALENCE_LOADER_SPEC",
    "RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_FINGERPRINT",
    "RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_SPEC",
    "RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_FINGERPRINT",
    "RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_SPEC",
    "build_issue56_production_semantic_retrieval_handler",
    "load_issue56_sealed_source_diagnostic_input",
    "load_issue56_real_prompt_sealed_source_diagnostic_input",
    "load_issue56_relation_projection_equivalence_diagnostic_input",
    "load_issue56_relation_projection_equivalence_v6_diagnostic_input",
    "load_issue56_relation_projection_offline_equivalence_v7_diagnostic_input",
]
