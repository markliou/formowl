"""Environment-bound adapter for the Issue #56 sealed-source diagnostic.

The CLI resolves this module by ``module:function``.  Source loading remains in
``formowl_mail.issue56_sealed_source`` so the mail owner path never imports the
gateway contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from email.headerregistry import HeaderRegistry
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Final

from formowl_auth.security import normalize_verified_email
from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    Observation,
    redact_public_raw_references,
    sha256_json,
)
from formowl_mail.answer import build_authorized_candidate_table_lookup, interpret_authorized_candidate_table_query, render_governed_evidence_answer
from formowl_mail.exact import (
    AuthorizedSourceOccurrence,
    SourceOccurrenceProvider,
    authorized_source_occurrence_scope_fingerprint,
    source_occurrence_column_capability_hash,
    source_occurrence_projection_capability_hash,
)
from formowl_mail.issue56_sealed_source import (
    APPROVER_ACTOR,
    ARTIFACT_ID as SEALED_SOURCE_LOAD_ARTIFACT_ID,
    IDENTITY_SCOPE_MODE,
    SOURCE_GRAPH_POLICY_ID,
    WORKSPACE_ID,
    load_issue56_sealed_source,
)
from formowl_mail.hybrid import (
    AdaptiveQueryPlanner,
    attach_authorized_source_occurrence_providers,
    execute_bounded_adaptive_query,
)
from formowl_mail.query import (
    MailAttachmentChildOccurrenceLineage,
    MailEvidenceQueryResult,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import authorized_permission_scope_matches

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
_SUPPLEMENTAL_OBSERVATION_ENVIRONMENT_FIELDS: Final[dict[str, str]] = {
    "supplemental_observation_artifact_path": (
        "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_PATH"
    ),
    "expected_supplemental_observation_artifact_sha256": (
        "FORMOWL_ISSUE56_SUPPLEMENTAL_OBSERVATION_ARTIFACT_SHA256"
    ),
    "supplemental_parent_snapshot_path": (
        "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_PATH"
    ),
    "expected_supplemental_parent_snapshot_sha256": (
        "FORMOWL_ISSUE56_SUPPLEMENTAL_PARENT_SNAPSHOT_SHA256"
    ),
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
_SOURCE_SCHEMA_CAPABILITY_MANIFEST_PATH_ENV: Final[str] = (
    "FORMOWL_ISSUE56_SOURCE_SCHEMA_CAPABILITY_MANIFEST_PATH"
)
_SOURCE_SCHEMA_CAPABILITY_MANIFEST_SHA256_ENV: Final[str] = (
    "FORMOWL_ISSUE56_SOURCE_SCHEMA_CAPABILITY_MANIFEST_SHA256"
)
_SOURCE_SCHEMA_CAPABILITY_MANIFEST_ARTIFACT_ID: Final[str] = (
    "formowl_issue56_sealed_source_schema_capability_candidate_manifest_v2"
)
_SOURCE_SCHEMA_CAPABILITY_POLICY_ID: Final[str] = (
    "source_schema_capability_candidate_only_unreviewed_v2"
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
    safe_binding = _validated_owner_safe_binding(
        loaded.safe_binding,
        source_session_binding_fingerprint=(
            loaded.session.source_session_binding_fingerprint
        ),
    )
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
    safe_binding = _validated_owner_safe_binding(
        loaded.safe_binding,
        source_session_binding_fingerprint=(
            loaded.session.source_session_binding_fingerprint
        ),
    )
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
    safe_binding = _validated_owner_safe_binding(
        loaded.safe_binding,
        source_session_binding_fingerprint=(
            loaded.session.source_session_binding_fingerprint
        ),
    )
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
    safe_binding = _validated_owner_safe_binding(
        loaded.safe_binding,
        source_session_binding_fingerprint=(
            loaded.session.source_session_binding_fingerprint
        ),
    )
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


def _load_approved_sealed_source(
    *,
    include_participant_authorization_observations: bool = False,
) -> Any:
    values: dict[str, str | Path] = {}
    for field_name, environment_name in _ENVIRONMENT_FIELDS.items():
        value = os.environ.get(environment_name)
        if value is None or not value.strip():
            raise ContractValidationError(
                f"sealed source loader environment is incomplete: {environment_name}"
            )
        values[field_name] = Path(value) if field_name in _PATH_FIELDS else value
    supplemental_values = {
        field_name: os.environ.get(environment_name, "").strip()
        for field_name, environment_name in (
            _SUPPLEMENTAL_OBSERVATION_ENVIRONMENT_FIELDS.items()
        )
    }
    if any(supplemental_values.values()) and not all(supplemental_values.values()):
        raise ContractValidationError(
            "sealed source supplemental observation environment is incomplete"
        )
    if all(supplemental_values.values()):
        values.update(
            {
                field_name: Path(value) if field_name.endswith("_path") else value
                for field_name, value in supplemental_values.items()
            }
        )

    return load_issue56_sealed_source(
        **values,
        identity_scope_mode=IDENTITY_SCOPE_MODE,
        workspace_id=WORKSPACE_ID,
        approver_actor=APPROVER_ACTOR,
        requester_user_id=APPROVER_ACTOR,
        include_participant_authorization_observations=(
            include_participant_authorization_observations
        ),
    )


def build_issue56_production_semantic_retrieval_handler(
    *,
    query_agent_planner: AdaptiveQueryPlanner | None = None,
) -> Callable[..., dict[str, Any]]:
    """Build the opt-in production handler over the approved sealed source."""

    loaded = _load_approved_sealed_source(
        include_participant_authorization_observations=True
    )
    safe_binding = _validated_owner_safe_binding(
        loaded.safe_binding,
        source_session_binding_fingerprint=(
            loaded.session.source_session_binding_fingerprint
        ),
    )
    providers = _build_mail_source_occurrence_providers(loaded, safe_binding=safe_binding)
    session = attach_authorized_source_occurrence_providers(
        loaded.session,
        providers,
    )
    graph_view = loaded.effective_graph_view
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
    lineaged_observation_ids = {
        lineage.source_observation_id for lineage in session.occurrence_lineages
    }
    lineage_validation_observations = tuple(
        observation
        for observation in session.authorized_observations
        if (
            observation.observation_id in lineaged_observation_ids
            or observation.observation_type in {"table_row", "table_cell"}
            or (
                observation.observation_type == "email_attachment_occurrence"
                and "child_asset_id" in (observation.payload or {})
            )
        )
    )
    lineage_validation_observation_ids = {
        observation.observation_id
        for observation in lineage_validation_observations
    }
    excluded_lineage_observations = tuple(
        observation
        for observation in session.authorized_observations
        if observation.observation_id not in lineage_validation_observation_ids
    )
    if any(
        observation.modality != "mail"
        or observation.observation_type != "mail_folder_occurrence"
        for observation in excluded_lineage_observations
    ):
        raise ContractValidationError("production evidence lineage binding is invalid")
    normalized_lineages = normalized_authorized_observation_lineages(
        lineage_validation_observations,
        authorized_source=session.authorized_source,
        occurrence_lineages=session.occurrence_lineages,
    )
    if normalized_lineages != session.occurrence_lineages:
        raise ContractValidationError("production evidence lineage binding is invalid")
    candidate_ledger = _build_candidate_table_ledger(session)
    candidate_lookup = (None if candidate_ledger is None else build_authorized_candidate_table_lookup(
        session=session, ledger=candidate_ledger))
    observation_by_id = {item.observation_id: item for item in session.authorized_observations}
    observations_by_hash: dict[str, list[Observation]] = {}
    for observation_id, observation_hash in session.authorized_observation_hashes:
        if observation_id in observation_by_id:
            observations_by_hash.setdefault(observation_hash, []).append(
                observation_by_id[observation_id]
            )
    lineage_by_observation_id = {
        item.source_observation_id: item for item in session.occurrence_lineages
    }

    def project_evidence(result: Any, *, limit: int) -> tuple[list[dict[str, Any]], int]:
        hashes = [*result.answer_citation_hashes,
                  *(score.source_observation_hash for score in result.scores)]
        if result.exact_result is not None:
            for item in result.exact_result.items:
                hashes.extend(item.cited_observation_hashes)
                hashes.extend(value[0] for value in item.governed_references)
        evidence: list[dict[str, Any]] = []
        redaction_count = 0
        for citation_hash in dict.fromkeys(hashes):
            if citation_hash not in observations_by_hash:
                raise ContractValidationError("production evidence authorization binding is invalid")
            for observation in sorted(
                observations_by_hash[citation_hash],
                key=lambda item: item.observation_id,
            ):
                lineage = lineage_by_observation_id.get(observation.observation_id)
                if lineage is None:
                    raise ContractValidationError(
                        "production evidence lineage binding is invalid"
                    )
                source_text = observation.text or observation.caption or ""
                if not source_text:
                    continue
                snippet, redacted = redact_public_raw_references(source_text)
                evidence.append({
                    "snippet": snippet[:400],
                    "citation_hash": citation_hash,
                    "occurrence_lineage_fingerprint": lineage.lineage_fingerprint,
                    **({"content_redacted": True} if redacted else {}),
                })
                redaction_count += redacted
                if len(evidence) == limit:
                    return evidence, redaction_count
        return evidence, redaction_count

    def project_query_agent_context(
        results: tuple[Any, ...],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        contexts = []
        citations = set(payload["context_bundle"]["citation_hashes"])
        lineages = set(payload["context_bundle"]["lineage_fingerprints"])
        redaction_count = 0
        for result in results:
            evidence, redacted = project_evidence(result, limit=4)
            exact_items = (
                [item.to_safe_dict() for item in result.exact_result.items[:4]]
                if result.exact_result is not None
                else []
            )
            contexts.append({
                "query_hash": result.query_hash,
                "status": result.status,
                "query_class": result.query_class,
                "evidence": evidence,
                "exact_items": exact_items,
            })
            citations.update(item["citation_hash"] for item in evidence)
            lineages.update(
                item["occurrence_lineage_fingerprint"] for item in evidence
            )
            redaction_count += redacted
        context = {
            **payload["context_bundle"],
            "citation_hashes": sorted(citations),
            "lineage_fingerprints": sorted(lineages),
            "successful_subqueries": contexts,
            "redacted_value_count": redaction_count,
        }
        context["bundle_fingerprint"] = sha256_json(context)
        return {**payload, "context_bundle": context}

    def retrieval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
        required_arguments = {
            "query_text",
            "requester_user_id",
            "session_id",
            "workspace_id",
        }
        if not required_arguments <= set(arguments) or set(arguments) - required_arguments - {
            "exact_inventory_kind",
            "exact_field",
            "page_size",
            "cursor",
        }:
            raise ContractValidationError("production semantic arguments are invalid")
        if (
            arguments["requester_user_id"] != session.requester_user_id
            or arguments["workspace_id"] != session.workspace_id
            or not isinstance(arguments["session_id"], str)
            or not arguments["session_id"]
        ):
            raise ContractValidationError("production semantic actor binding mismatch")
        result, successful_results, query_agent_payload = execute_bounded_adaptive_query(
            session=session,
            query_text=arguments["query_text"],
            effective_graph_view=graph_view,
            allowed_relation_types=relation_types,
            exact_inventory_kind=arguments.get("exact_inventory_kind"),
            exact_field=arguments.get("exact_field"),
            page_size=arguments.get("page_size", 20),
            cursor=arguments.get("cursor"),
            planner=query_agent_planner,
        )
        query_agent_payload = project_query_agent_context(
            successful_results, query_agent_payload
        )
        exact_result = result.exact_result
        exact_inventory_kind = arguments.get("exact_inventory_kind")
        if (
            isinstance(exact_inventory_kind, str)
            and exact_inventory_kind.strip()
            and (
                exact_result is None
                or exact_result.source_occurrence_page is None
            )
        ):
            raise ContractValidationError(
                "production exact inventory result is unavailable"
            )
        candidate = (interpret_authorized_candidate_table_query(session=session,
            query_text=arguments["query_text"], lookup=candidate_lookup)
            if candidate_lookup is not None and exact_result is None
            and not result.answer_citation_hashes else None)
        if candidate is not None:
            candidate_payload = {**candidate.to_safe_dict(),
                                 "structure_status": "candidate_only"}
            citation_hashes = [item["observation_hash"]
                               for item in candidate_payload["governed_citations"]]
            if len(citation_hashes) != 4 or len(set(citation_hashes)) != 4:
                raise ContractValidationError("production candidate citation binding is invalid")
            payload = {
                "status": candidate.status,
                "answer": {
                    "status": candidate.status, "text": f"{candidate.header}: {candidate.value}",
                    "header": candidate.header, "value": candidate.value,
                    "answer_hash": sha256_json(candidate_payload),
                    "source_result_fingerprint": candidate.result_fingerprint,
                    "citation_count": 4},
                "candidate_interpretation": candidate_payload,
                "query_agent": query_agent_payload,
                "citations": citation_hashes, "evidence": [],
                "graph_hits": {"count": result.graph_path_count},
                "canonical_kg": False, "deterministic_exact": False, "exact_result": None,
                "redaction_counts": {"redacted_value_count": 0}}
            validate_public_gateway_payload(payload); return payload
        evidence, redaction_count = project_evidence(result, limit=10)
        evidence_result = MailEvidenceQueryResult(
            status="ok",
            mail_import_session_id=None,
            query_hash=result.query_hash,
            evidence_snippets=evidence,
            redaction_counts={"redacted_value_count": redaction_count},
        ).to_dict()
        evidence = evidence_result["evidence_snippets"]
        answer = render_governed_evidence_answer(
            result,
            evidence_count=len(evidence),
        )
        public_citations = list(
            dict.fromkeys(
                (
                    *answer.citation_hashes,
                    *(item["citation_hash"] for item in evidence),
                )
            )
        )
        if exact_result is not None and exact_result.source_occurrence_page is not None:
            page = exact_result.source_occurrence_page
            selected_providers = tuple(
                provider
                for provider in providers
                if provider.provider_fingerprint == page["provider_fingerprint"]
            )
            if len(selected_providers) != 1:
                raise ContractValidationError(
                    "production source occurrence provider binding is invalid"
                )
            provider = selected_providers[0]
            payload = {
                "status": result.status,
                "exact_inventory": {
                    "status": exact_result.status,
                    "query_class": result.query_class,
                    "plan": {
                        "plan_fingerprint": result.plan_fingerprint,
                        "resource_kind": provider.resource_kind,
                        "normalized_field": provider.normalized_field,
                        "predicate": provider.predicate,
                        "operator": provider.operator,
                        "claim_strength": result.claim_strength,
                        "duplicate_policy": provider.duplicate_policy,
                        "ordering": "item_hash_ascending_v1",
                        "page_size": page["page_size"],
                        "cursor_present": page["cursor_present"],
                    },
                    "total_count": exact_result.exact_count,
                    "returned_count": exact_result.returned_item_count,
                    "coverage_status": page["coverage_status"],
                    "next_cursor": page["next_cursor"],
                    "redacted_count": page["redacted_count"],
                    "unsupported_count": page["unsupported_count"],
                    "encrypted_count": page.get("encrypted_count", 0),
                    "unresolved_count": page["unresolved_count"],
                    "authorized_occurrence_scope_count": page.get(
                        "authorized_occurrence_scope_count"
                    ),
                    "extractable_occurrence_scope_count": page.get(
                        "extractable_occurrence_scope_count"
                    ),
                    "candidate_only_occurrence_count": page.get(
                        "candidate_only_occurrence_count",
                        0,
                    ),
                    "source_asset_reason_counts": page.get(
                        "source_asset_reason_counts",
                        [],
                    ),
                    "duplicate_policy": provider.duplicate_policy,
                    "ambiguous_identifier_count": page["ambiguous_identifier_count"],
                    "items": [
                        {
                            "item_hash": item.item_hash,
                            "governed_references": [
                                {
                                    "citation_hash": citation_hash,
                                    "occurrence_lineage_fingerprint": lineage_fingerprint,
                                }
                                for citation_hash, lineage_fingerprint in item.governed_references
                            ],
                            "matched_normalized_value_hashes": list(
                                item.matched_normalized_value_hashes
                            ),
                            "ambiguous_identifier": item.ambiguous_identifier,
                            **(
                                {
                                    "structure_status": item.structure_status,
                                    "structured_values": [
                                        {
                                            "field": field,
                                            "value": value,
                                            "citation_hash": citation_hash,
                                            "occurrence_lineage_fingerprint": (
                                                lineage_fingerprint
                                            ),
                                        }
                                        for (
                                            field,
                                            value,
                                            citation_hash,
                                            lineage_fingerprint,
                                        ) in item.structured_values
                                    ],
                                }
                                if item.structured_values
                                else {}
                            ),
                        }
                        for item in exact_result.items
                    ],
                },
                "citations": list(result.answer_citation_hashes),
                "query_agent": query_agent_payload,
                "redaction_counts": {"redacted_value_count": page["redacted_count"]},
            }
            validate_public_gateway_payload(payload)
            return payload
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
                "citation_count": len(public_citations),
            },
            "evidence": evidence,
            "citations": public_citations,
            "query_agent": query_agent_payload,
            "graph_hits": {"count": result.graph_path_count},
            "relationship": {
                "relation_types": sorted(projected_relation_types),
                "path_count": len(result.graph_paths),
                "max_hops": max((path.hop_count for path in result.graph_paths), default=0),
            },
            "redaction_counts": {"redacted_value_count": redaction_count},
        }
        validate_public_gateway_payload(payload)
        return payload

    return retrieval_handler


def _build_candidate_table_ledger(session: Any) -> dict[str, Any] | None:
    hashes = dict(session.authorized_observation_hashes)
    lineages = {
        item.source_observation_id: item
        for item in session.occurrence_lineages
        if isinstance(item, MailAttachmentChildOccurrenceLineage)
    }
    cells_by_row: dict[tuple[Any, ...], list[Observation]] = {}
    groups: dict[tuple[Any, ...], list[Observation]] = {}
    for item in session.authorized_observations:
        structure = (item.payload or {}).get("table_structure")
        if (item.modality != "document" or not isinstance(structure, Mapping)
                or structure.get("structure_status") != "candidate_only"
                or item.observation_id not in lineages):
            continue
        if item.observation_type == "table_cell":
            cells_by_row.setdefault(_table_row_key(item), []).append(item)
        elif item.observation_type == "table_row":
            key = (item.asset_id, item.location.get("sheet_name"),
                   item.location.get("table_index"), structure.get("header_row_index"))
            groups.setdefault(key, []).append(item)
    if not groups:
        return None
    def reference(item: Observation, *, column: int | None = None) -> dict[str, Any]:
        result = {"observation_id": item.observation_id,
                  "observation_hash": hashes[item.observation_id],
                  "lineage_fingerprint": lineages[item.observation_id].lineage_fingerprint}
        return result if column is None else {
            **result, "column_ordinal": column, "value_hash": sha256_json(item.text)}
    tables = []
    for key, grouped_rows in sorted(groups.items(), key=lambda item: repr(item[0])):
        rows = sorted(grouped_rows, key=lambda item: item.location["row_index"])
        header = next(
            (row for row in rows if row.location.get("row_index") == key[-1]),
            None,
        )
        if header is None:
            raise ContractValidationError("candidate table header is unavailable")
        ledger_rows = []
        for row in rows:
            cells = sorted(cells_by_row.get(_table_row_key(row), ()),
                           key=lambda item: item.location.get("cell_index", 0))
            ledger_rows.append({**reference(row), "cells": tuple(
                reference(cell, column=cell.location["cell_index"]) for cell in cells)})
        header_cells = {item["column_ordinal"]: item for item in ledger_rows[0]["cells"]}
        tables.append({"structure_status": "candidate_only", "table_fingerprint": sha256_json(key),
                       "rows": tuple(ledger_rows),
                       "header_hypotheses": tuple(
                           header_cells[column["cell_index"]]
                           for column in header.payload["table_structure"]["columns"])})
    payload = {"artifact_id": "formowl_candidate_table_ledger_v1",
               "structure_status": "candidate_only", "tables": tuple(tables)}
    return {**payload, "ledger_fingerprint": sha256_json(payload)}


def _build_mail_source_occurrence_providers(
    loaded: Any,
    *,
    safe_binding: Mapping[str, Any],
) -> tuple[SourceOccurrenceProvider, ...]:
    snapshot_path = Path(os.environ["FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_PATH"])
    snapshot_bytes = snapshot_path.read_bytes()
    byte_sha256 = "sha256:" + hashlib.sha256(snapshot_bytes).hexdigest()
    try:
        snapshot = json.loads(snapshot_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError("production retrieval snapshot is invalid") from exc
    if (
        not isinstance(snapshot, Mapping)
        or byte_sha256 != os.environ["FORMOWL_ISSUE56_RETRIEVAL_SNAPSHOT_SHA256"]
        or byte_sha256 != safe_binding["retrieval_snapshot_byte_sha256"]
        or snapshot.get("snapshot_fingerprint")
        != safe_binding["retrieval_snapshot_fingerprint"]
        or snapshot.get("source_snapshot_fingerprint")
        != safe_binding["source_snapshot_fingerprint"]
        or _contains_tenant_id(snapshot)
    ):
        raise ContractValidationError("production retrieval snapshot binding is invalid")

    session = loaded.session
    if session.authorized_source is None:
        raise ContractValidationError("production authorized source is unavailable")
    if "supplemental_observation_partition_status" in safe_binding:
        authorized_source = session.authorized_source
        authorized_permission_scopes = authorized_source.authorized_permission_scopes
        if (
            safe_binding["supplemental_observation_partition_status"] != "loaded"
            or len(session.authorized_source_scope_ids) != 1
            or authorized_source.workspace_id != session.workspace_id
            or authorized_source.source_scope_ids
            != session.authorized_source_scope_ids
            or len(authorized_permission_scopes) != 1
            or authorized_permission_scopes[0].scope_id
            != session.authorized_source_scope_ids[0]
            or not authorized_permission_scope_matches(
                authorized_permission_scopes[0],
                authorized_source=authorized_source,
            )
        ):
            raise ContractValidationError(
                "production supplemental observation binding is invalid"
            )
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=session.requester_user_id,
            workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_observation_hashes=session.authorized_observation_hashes,
            source_session_binding_fingerprint=(
                session.source_session_binding_fingerprint or ""
            ),
        )
        table_provider = _build_attachment_table_row_provider(
            session,
            authorized_scope_fingerprint=scope_fingerprint,
        )
        if table_provider is None or not table_provider.occurrences:
            raise ContractValidationError(
                "production supplemental table provider is unavailable"
            )
        return (table_provider,)
    authorized_observation_hashes = dict(session.authorized_observation_hashes)
    item_lineage_by_occurrence: dict[str, str] = {}
    for lineage in session.occurrence_lineages:
        existing = item_lineage_by_occurrence.get(lineage.occurrence_id)
        if existing is None or lineage.lineage_fingerprint < existing:
            item_lineage_by_occurrence[lineage.occurrence_id] = lineage.lineage_fingerprint
    authorized_asset_ids = {observation.asset_id for observation in session.authorized_observations}
    permission_fingerprints = {
        sha256_json(observation.permission_scope) for observation in session.authorized_observations
    }
    any_field = "participant.any.local_part"
    direct_identifier_field = "message_occurrence.direct_source_identifier_v1"
    field_by_role = {
        role: f"participant.{role}.local_part" for role in ("from", "sender", "to", "cc")
    }
    value_bindings = {field: {} for field in (any_field, *field_by_role.values())}
    unresolved_occurrence_ids = {field: set() for field in value_bindings}
    mailbox_header_registry = HeaderRegistry()
    direct_identifier_bindings: dict[
        str,
        set[tuple[str, str, str, str]],
    ] = {}
    rows = snapshot.get("parsed_mail_observations")
    if not isinstance(rows, list):
        raise ContractValidationError("production source occurrence inventory is unavailable")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ContractValidationError("production source occurrence row is invalid")
        payload = row.get("payload")
        location = row.get("location")
        if not isinstance(payload, Mapping) or not isinstance(location, Mapping):
            continue
        occurrence_id = location.get("message_occurrence_id")
        if occurrence_id not in item_lineage_by_occurrence:
            continue
        role = str(payload.get("header_name", "")).casefold()
        if row.get("observation_type") == "email_header" and role in field_by_role:
            value = str(payload.get("header_value", ""))
            mailbox_header_name = role
            fields = (any_field, field_by_role[role])
        elif row.get("observation_type") == "email_message":
            value = str(payload.get("sender", ""))
            mailbox_header_name = "from"
            fields = (any_field,)
        else:
            continue
        observation = Observation.from_dict(dict(row))
        if (
            observation.asset_id not in authorized_asset_ids
            or sha256_json(observation.permission_scope) not in permission_fingerprints
        ):
            raise ContractValidationError("production participant evidence is unauthorized")
        lineage = source_occurrence_lineage_from_observation(
            observation,
            authorized_source=session.authorized_source,
        )
        if lineage.occurrence_id != occurrence_id:
            raise ContractValidationError("production participant lineage is invalid")
        citation_hash = sha256_json(observation.to_dict())
        if authorized_observation_hashes.get(observation.observation_id) != citation_hash:
            raise ContractValidationError(
                "production participant Observation binding is unauthorized"
            )
        try:
            parsed_header = mailbox_header_registry(mailbox_header_name, value)
            parsed_addresses = tuple(parsed_header.addresses)
            if parsed_header.defects or not parsed_addresses:
                raise ContractValidationError(
                    "participant mailbox list is incomplete"
                )
            normalized_addresses = tuple(
                normalize_verified_email(address.addr_spec)
                for address in parsed_addresses
            )
        except (AttributeError, ContractValidationError, TypeError, ValueError):
            for field in fields:
                unresolved_occurrence_ids[field].add(str(occurrence_id))
            continue
        for normalized_address in normalized_addresses:
            binding = (
                sha256_json(normalized_address.split("@", 1)[0]),
                sha256_json(normalized_address),
                citation_hash,
                lineage.lineage_fingerprint,
            )
            for field in fields:
                value_bindings[field].setdefault(str(occurrence_id), set()).add(
                    binding
                )

    mention_batch = loaded.identifier_mention_batch
    graph_build = loaded.graph_build
    if (
        mention_batch.identity_scope_mode != IDENTITY_SCOPE_MODE
        or mention_batch.workspace_id != session.workspace_id
        or mention_batch.tenant_id is not None
        or mention_batch.occurrence_count != len(mention_batch.candidate_mentions)
        or graph_build.identifier_mention_count != mention_batch.occurrence_count
        or graph_build.authorized_identifier_mention_count
        != mention_batch.occurrence_count
        or safe_binding["source_identifier_mention_batch_fingerprint"]
        != mention_batch.batch_fingerprint
    ):
        raise ContractValidationError(
            "production direct source identifier batch binding is invalid"
        )
    retrieval_observation_hashes = dict(session.retrieval_observation_hashes)
    observation_by_id = {
        observation.observation_id: observation
        for observation in session.authorized_observations
    }
    lineage_by_observation_id = {
        lineage.source_observation_id: lineage
        for lineage in session.occurrence_lineages
    }
    admitted_occurrence_ids: set[str] = set()
    for observation_id, observation_hash in retrieval_observation_hashes.items():
        observation = observation_by_id.get(observation_id)
        if observation is None or sha256_json(observation.to_dict()) != observation_hash:
            raise ContractValidationError(
                "production direct source identifier retrieval binding is invalid"
            )
        if observation.modality == "mail":
            admitted_occurrence_ids.add(
                source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=session.authorized_source,
                ).occurrence_id
            )
            continue
        child_lineage = lineage_by_observation_id.get(observation_id)
        if (
            observation.modality != "document"
            or observation.observation_type != "table_row"
            or not isinstance(child_lineage, MailAttachmentChildOccurrenceLineage)
            or child_lineage.observation_type != "table_row"
            or child_lineage.child_asset_id != observation.asset_id
        ):
            raise ContractValidationError(
                "production source occurrence retrieval modality is invalid"
            )
    authorized_occurrence_ids = set(item_lineage_by_occurrence)
    full_source_occurrence_ids = {
        occurrence.message_occurrence_id
        for occurrence in loaded.source_bundle.message_occurrences
    }
    if (
        len(full_source_occurrence_ids)
        != len(loaded.source_bundle.message_occurrences)
        or authorized_occurrence_ids != full_source_occurrence_ids
        or not admitted_occurrence_ids <= authorized_occurrence_ids
    ):
        raise ContractValidationError(
            "production direct source identifier occurrence scope is invalid"
        )
    for raw_mention in mention_batch.candidate_mentions:
        mention = CandidateMention.from_dict(raw_mention.to_dict())
        if len(mention.source_observation_ids) != 1:
            raise ContractValidationError(
                "production direct source identifier Observation binding is invalid"
            )
        observation_id = mention.source_observation_ids[0]
        observation = observation_by_id.get(observation_id)
        exact_hash = mention.metadata.get("exact_protected_token_hash")
        if observation is None or not isinstance(exact_hash, str):
            raise ContractValidationError(
                "production direct source identifier evidence is unavailable"
            )
        citation_hash = sha256_json(observation.to_dict())
        lineage = source_occurrence_lineage_from_observation(
            observation,
            authorized_source=session.authorized_source,
        )
        stored_lineage = lineage_by_observation_id.get(observation_id)
        if (
            retrieval_observation_hashes.get(observation_id) != citation_hash
            or authorized_observation_hashes.get(observation_id) != citation_hash
            or mention.normalized_label != exact_hash
            or mention.text_hash != exact_hash
            or mention.metadata.get("candidate_kind")
            != "protected_identifier_occurrence"
            or mention.metadata.get("candidate_only") is not True
            or mention.metadata.get("canonical_write_allowed") is not False
            or mention.metadata.get("source_observation_fingerprint")
            != citation_hash
            or mention.metadata.get("permission_boundary_fingerprint")
            != sha256_json(observation.permission_scope)
            or mention.metadata.get("message_occurrence_fingerprint")
            != sha256_json(lineage.occurrence_id)
            or stored_lineage is None
            or stored_lineage.lineage_fingerprint != lineage.lineage_fingerprint
        ):
            raise ContractValidationError(
                "production direct source identifier lineage binding is invalid"
            )
        if mention.mention_type != "protected_identifier:business_identifier":
            continue
        direct_identifier_bindings.setdefault(
            lineage.occurrence_id,
            set(),
        ).add(
            (
                exact_hash,
                exact_hash,
                citation_hash,
                lineage.lineage_fingerprint,
            )
        )
    if not set(direct_identifier_bindings) <= admitted_occurrence_ids:
        raise ContractValidationError(
            "production direct source identifier occurrence scope is invalid"
        )
    direct_unresolved_count = len(
        authorized_occurrence_ids - set(direct_identifier_bindings)
    )

    scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        source_scope_ids=session.authorized_source_scope_ids,
        authorized_observation_hashes=session.authorized_observation_hashes,
        source_session_binding_fingerprint=session.source_session_binding_fingerprint or "",
    )
    has_attachment_table_rows = any(
        observation.modality == "document"
        and observation.observation_type == "table_row"
        for observation in session.authorized_observations
    ) and any(
        observation.observation_type == "email_attachment_occurrence"
        for observation in session.authorized_observations
    )
    table_capability_mapping = (
        _load_source_schema_capability_mapping(
            session,
            safe_binding=safe_binding,
            authorized_scope_fingerprint=scope_fingerprint,
        )
        if has_attachment_table_rows
        else None
    )
    participant_providers_list: list[SourceOccurrenceProvider] = []
    for field, bindings_by_occurrence in value_bindings.items():
        clean_bindings_by_occurrence = {
            occurrence_id: bindings
            for occurrence_id, bindings in bindings_by_occurrence.items()
            if occurrence_id not in unresolved_occurrence_ids[field]
        }
        participant_providers_list.append(
            SourceOccurrenceProvider(
                provider_id="mail_source_occurrence_provider_v1",
                inventory_kind_alias="mail_observation",
                resource_kind="mail_message_occurrence",
                normalized_field=field,
                predicate="source_occurrence_involves",
                operator="case_insensitive_exact",
                requester_user_id=session.requester_user_id,
                workspace_id=session.workspace_id,
                source_scope_ids=session.authorized_source_scope_ids,
                authorized_scope_fingerprint=scope_fingerprint,
                occurrences=tuple(
                    AuthorizedSourceOccurrence(
                        item_hash=sha256_json(
                            [
                                "mail_message_occurrence",
                                item_lineage_by_occurrence[occurrence_id],
                            ]
                        ),
                        value_bindings=tuple(sorted(bindings)),
                    )
                    for occurrence_id, bindings in sorted(
                        clean_bindings_by_occurrence.items()
                    )
                ),
                unresolved_count=len(
                    authorized_occurrence_ids - set(clean_bindings_by_occurrence)
                ),
            )
        )
    participant_providers = tuple(participant_providers_list)
    direct_identifier_provider = SourceOccurrenceProvider(
        provider_id=(
            "mail_message_occurrence_direct_source_identifier_provider_v1"
        ),
        inventory_kind_alias="mail_observation",
        resource_kind="mail_message_occurrence",
        normalized_field=direct_identifier_field,
        predicate="source_occurrence_involves",
        operator="case_insensitive_exact",
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        source_scope_ids=session.authorized_source_scope_ids,
        authorized_scope_fingerprint=scope_fingerprint,
        occurrences=tuple(
            AuthorizedSourceOccurrence(
                item_hash=sha256_json(
                    [
                        "mail_message_occurrence",
                        item_lineage_by_occurrence[occurrence_id],
                    ]
                ),
                value_bindings=tuple(sorted(bindings)),
            )
            for occurrence_id, bindings in sorted(
                direct_identifier_bindings.items()
            )
        ),
        unresolved_count=direct_unresolved_count,
    )
    table_row_provider = _build_attachment_table_row_provider(
        session,
        authorized_scope_fingerprint=scope_fingerprint,
        source_schema_capability_mapping=table_capability_mapping,
    )
    return (
        *participant_providers,
        direct_identifier_provider,
        *((table_row_provider,) if table_row_provider is not None else ()),
    )


def _build_attachment_table_row_provider(
    session: Any,
    *,
    authorized_scope_fingerprint: str,
    source_schema_capability_mapping: Mapping[str, frozenset[str]] | None = None,
) -> SourceOccurrenceProvider | None:
    observations = tuple(session.authorized_observations)
    parents = tuple(
        observation
        for observation in observations
        if observation.observation_type == "email_attachment_occurrence"
    )
    rows = tuple(
        observation
        for observation in observations
        if observation.modality == "document"
        and observation.observation_type == "table_row"
    )
    if not parents or not rows:
        return None
    authorized_hashes = dict(session.authorized_observation_hashes)
    lineage_by_id = {
        lineage.source_observation_id: lineage
        for lineage in session.occurrence_lineages
    }
    parent_by_child_asset: dict[str, Observation] = {}
    for parent in parents:
        child_asset_id = (parent.payload or {}).get("child_asset_id")
        if child_asset_id is None:
            continue
        if (
            not isinstance(child_asset_id, str)
            or not child_asset_id
            or child_asset_id in parent_by_child_asset
        ):
            raise ContractValidationError(
                "production attachment table parent binding is invalid"
            )
        parent_by_child_asset[child_asset_id] = parent
    cells_by_row: dict[tuple[Any, ...], list[Observation]] = {}
    for cell in observations:
        if cell.modality != "document" or cell.observation_type != "table_cell":
            continue
        cells_by_row.setdefault(_table_row_key(cell), []).append(cell)

    provider_occurrences: list[AuthorizedSourceOccurrence] = []
    bound_parent_ids: set[str] = set()
    authorized_row_scope_count = 0
    unresolved_row_count = 0
    tokenizer_profile = session.index._runtime_components.tokenizer_profile
    observed_source_schema_capabilities: dict[str, set[str]] = {}
    for row in sorted(rows, key=lambda item: item.observation_id):
        parent = parent_by_child_asset.get(row.asset_id or "")
        row_hash = authorized_hashes.get(row.observation_id)
        row_lineage = lineage_by_id.get(row.observation_id)
        structure = (row.payload or {}).get("table_structure")
        if (
            parent is None
            or not isinstance(row_hash, str)
            or row_lineage is None
            or not isinstance(structure, Mapping)
        ):
            raise ContractValidationError(
                "production attachment table row binding is invalid"
            )
        structure_status = structure.get("structure_status")
        row_role = structure.get("row_role")
        if structure_status not in {
            "source_provided",
            "candidate_only",
            "unavailable",
        }:
            raise ContractValidationError(
                "production attachment table structure is invalid"
            )
        bound_parent_ids.add(parent.observation_id)
        if structure_status == "source_provided" and row_role in {
            "header",
            "totals",
        }:
            continue
        authorized_row_scope_count += 1
        if structure_status == "unavailable" or row_role == "header_candidate":
            unresolved_row_count += 1
            continue
        row_cells = sorted(
            cells_by_row.get(_table_row_key(row), ()),
            key=lambda item: int(item.location.get("cell_index", 0)),
        )
        if not row_cells or len(row_cells) > 64:
            unresolved_row_count += 1
            continue
        value_bindings: set[tuple[str, str, str, str]] = set()
        projection_bindings: list[tuple[str, str, str, str]] = []
        structured_column_bindings: set[
            tuple[str, str, str, str, str, str, str]
        ] = set()
        for cell in row_cells:
            cell_hash = authorized_hashes.get(cell.observation_id)
            cell_lineage = lineage_by_id.get(cell.observation_id)
            cell_structure = (cell.payload or {}).get("table_structure")
            if (
                not isinstance(cell_hash, str)
                or cell_lineage is None
                or not isinstance(cell_structure, Mapping)
                or cell_lineage.parent_occurrence_id
                != row_lineage.parent_occurrence_id
                or cell.permission_scope != row.permission_scope
            ):
                raise ContractValidationError(
                    "production attachment table cell binding is invalid"
                )
            cell_index = cell.location.get("cell_index")
            if not isinstance(cell_index, int) or isinstance(cell_index, bool):
                raise ContractValidationError(
                    "production attachment table cell location is invalid"
                )
            field = cell_structure.get("column_name")
            if not isinstance(field, str) or not field:
                field = f"column_{cell_index}"
            value = cell.text or ""
            safe_field, _ = redact_public_raw_references(field)
            safe_value, _ = redact_public_raw_references(value)
            safe_field = safe_field[:120]
            safe_value = safe_value[:400]
            projection_bindings.append(
                (
                    safe_field,
                    safe_value,
                    cell_hash,
                    cell_lineage.lineage_fingerprint,
                )
            )
            value_token_hashes = {
                sha256_json(token)
                for token in tokenizer_profile.analyze(value).tokens
                if token
            }
            if (
                structure_status == "source_provided"
                and cell_structure.get("structure_status") == "source_provided"
                and cell.text == ""
                and (cell.payload or {}).get("cell_state") == "absent"
                and isinstance(cell.location.get("row_index"), int)
                and not isinstance(cell.location.get("row_index"), bool)
            ):
                value_token_hashes.add(
                    sha256_json(["source_provided_structural_blank_value_v1"])
                )
            normalized_field = tokenizer_profile.normalize_exact_identifier_surface(
                safe_field
            )
            column_hash = source_occurrence_column_capability_hash(
                normalized_field
            )
            header_path = cell_structure.get("header_path", ())
            if not isinstance(header_path, (list, tuple)) or len(header_path) > 4:
                raise ContractValidationError(
                    "production attachment table header path is invalid"
                )
            header_surfaces: list[str] = []
            previous_header_row = 0
            row_index = cell.location.get("row_index")
            for component in header_path:
                if not isinstance(component, Mapping):
                    raise ContractValidationError(
                        "production attachment table header path is invalid"
                    )
                address = tuple(
                    component.get(key)
                    for key in (
                        "row_index",
                        "cell_index",
                        "min_row_index",
                        "max_row_index",
                        "min_column_index",
                        "max_column_index",
                    )
                )
                if (
                    not isinstance(row_index, int)
                    or isinstance(row_index, bool)
                    or any(
                        not isinstance(item, int) or isinstance(item, bool)
                        for item in address
                    )
                    or not (
                        0 < address[2] <= address[0] <= address[3] < row_index
                        and 0 < address[4] <= address[1] <= address[5]
                        and address[4] <= cell_index <= address[5]
                        and address[0] > previous_header_row
                    )
                ):
                    raise ContractValidationError(
                        "production attachment table header path is invalid"
                    )
                component_value = component.get("value")
                if not isinstance(component_value, str) or not component_value.strip():
                    raise ContractValidationError(
                        "production attachment table header path is invalid"
                    )
                safe_component, _ = redact_public_raw_references(component_value)
                normalized_component = (
                    tokenizer_profile.normalize_exact_identifier_surface(
                        safe_component[:120]
                    )
                )
                if not normalized_component:
                    raise ContractValidationError(
                        "production attachment table header path is invalid"
                    )
                header_surfaces.append(normalized_component)
                previous_header_row = address[0]
            candidate_surfaces = [safe_field, *header_surfaces]
            column_candidate_hashes = {
                sha256_json(field_token)
                for surface in candidate_surfaces
                for field_token in tokenizer_profile.analyze(surface).tokens
                if field_token
            }
            phrase_surfaces = list(header_surfaces)
            if not phrase_surfaces or phrase_surfaces[-1] != normalized_field:
                phrase_surfaces.append(normalized_field)
            for start in range(len(phrase_surfaces)):
                for end in range(start + 1, min(len(phrase_surfaces), start + 4) + 1):
                    phrase = "".join(phrase_surfaces[start:end])
                    column_candidate_hashes.add(sha256_json(phrase))
            if column_candidate_hashes:
                observed_source_schema_capabilities.setdefault(
                    column_hash,
                    set(),
                ).update(column_candidate_hashes)
                if source_schema_capability_mapping is not None:
                    sealed_candidates = source_schema_capability_mapping.get(
                        column_hash
                    )
                    if sealed_candidates is None:
                        raise ContractValidationError(
                            "production source schema capability coverage is incomplete"
                        )
                    column_candidate_hashes = set(sealed_candidates)
                for field_hash in column_candidate_hashes:
                    value_bindings.add(
                        (
                            field_hash,
                            source_occurrence_projection_capability_hash(field_hash),
                            cell_hash,
                            cell_lineage.lineage_fingerprint,
                        )
                    )
                for field_hash in column_candidate_hashes:
                    for value_hash in value_token_hashes:
                        structured_column_bindings.add(
                            (
                                column_hash,
                                field_hash,
                                value_hash,
                                safe_field,
                                safe_value,
                                cell_hash,
                                cell_lineage.lineage_fingerprint,
                            )
                        )
            value_token_hashes.add(
                sha256_json(["table_cell_projection", cell_hash])
            )
            for token_hash in value_token_hashes:
                value_bindings.add(
                    (
                        token_hash,
                        token_hash,
                        cell_hash,
                        cell_lineage.lineage_fingerprint,
                    )
                )
                value_bindings.add(
                    (
                        token_hash,
                        token_hash,
                        row_hash,
                        row_lineage.lineage_fingerprint,
                    )
                )
        provider_occurrences.append(
            AuthorizedSourceOccurrence(
                item_hash=sha256_json(
                    [
                        "attachment_table_row_occurrence",
                        row_hash,
                        row_lineage.lineage_fingerprint,
                    ]
                ),
                value_bindings=tuple(sorted(value_bindings)),
                projection_bindings=tuple(projection_bindings),
                structure_status=str(structure_status),
                structured_column_bindings=tuple(
                    sorted(structured_column_bindings)
                ),
            )
        )

    if source_schema_capability_mapping is not None and {
        column_hash: frozenset(candidate_hashes)
        for column_hash, candidate_hashes in observed_source_schema_capabilities.items()
    } != dict(source_schema_capability_mapping):
        raise ContractValidationError(
            "production source schema capability binding is invalid"
        )
    if source_schema_capability_mapping is not None:
        provider_occurrences = [
            replace(occurrence, structure_status="candidate_only")
            for occurrence in provider_occurrences
        ]

    source_asset_reason_counts: dict[str, int] = {}
    for parent in parents:
        status = (parent.payload or {}).get("attachment_extraction_status")
        if status in {"unsupported", "encrypted", "redacted"}:
            source_asset_reason_counts[str(status)] = (
                source_asset_reason_counts.get(str(status), 0) + 1
            )
        elif parent.observation_id not in bound_parent_ids:
            source_asset_reason_counts["unresolved"] = (
                source_asset_reason_counts.get("unresolved", 0) + 1
            )
    return SourceOccurrenceProvider(
        provider_id="attachment_table_row_source_occurrence_provider_v1",
        inventory_kind_alias="attachment_table_row",
        resource_kind="attachment_table_row_occurrence",
        normalized_field="table.row.cell_value",
        predicate="source_occurrence_row_contains",
        operator="case_insensitive_exact",
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        source_scope_ids=session.authorized_source_scope_ids,
        authorized_scope_fingerprint=authorized_scope_fingerprint,
        occurrences=tuple(provider_occurrences),
        filter_slot_policy="combined_present_intersection_v1",
        unresolved_count=unresolved_row_count,
        authorized_occurrence_scope_count=authorized_row_scope_count,
        extractable_occurrence_scope_count=len(provider_occurrences),
        source_asset_reason_counts=tuple(sorted(source_asset_reason_counts.items())),
    )


def _load_source_schema_capability_mapping(
    session: Any,
    *,
    safe_binding: Mapping[str, Any],
    authorized_scope_fingerprint: str,
) -> dict[str, frozenset[str]]:
    raw_path = os.environ.get(_SOURCE_SCHEMA_CAPABILITY_MANIFEST_PATH_ENV)
    expected_byte_sha256 = os.environ.get(
        _SOURCE_SCHEMA_CAPABILITY_MANIFEST_SHA256_ENV
    )
    if not raw_path or not expected_byte_sha256:
        raise ContractValidationError(
            "production source schema capability manifest is unavailable"
        )
    try:
        manifest_bytes = Path(raw_path).read_bytes()
    except OSError as exc:
        raise ContractValidationError(
            "production source schema capability manifest is unavailable"
        ) from exc
    byte_sha256 = "sha256:" + hashlib.sha256(manifest_bytes).hexdigest()
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractValidationError(
            "production source schema capability manifest is invalid"
        ) from exc
    if (
        not isinstance(manifest, Mapping)
        or byte_sha256 != expected_byte_sha256
        or _contains_tenant_id(manifest)
    ):
        raise ContractValidationError(
            "production source schema capability manifest binding is invalid"
        )
    expected_keys = {
        "artifact_id",
        "schema_version",
        "policy_id",
        "review_status",
        "human_review_complete",
        "identity_scope_mode",
        "workspace_fingerprint",
        "retrieval_snapshot_byte_sha256",
        "retrieval_snapshot_fingerprint",
        "source_snapshot_fingerprint",
        "source_session_binding_fingerprint",
        "authorized_scope_fingerprint",
        "provider_binding_fingerprint",
        "tokenizer_profile_fingerprint",
        "column_count",
        "candidate_hash_count",
        "columns",
        "mapping_fingerprint",
        "manifest_fingerprint",
    }
    columns = manifest.get("columns")
    tokenizer_profile = session.index._runtime_components.tokenizer_profile
    fingerprint_fields = (
        "workspace_fingerprint",
        "retrieval_snapshot_byte_sha256",
        "retrieval_snapshot_fingerprint",
        "source_snapshot_fingerprint",
        "source_session_binding_fingerprint",
        "authorized_scope_fingerprint",
        "provider_binding_fingerprint",
        "tokenizer_profile_fingerprint",
        "mapping_fingerprint",
        "manifest_fingerprint",
    )
    provider_binding_fingerprint = sha256_json(
        {
            "artifact_id": "attachment_table_row_provider_capability_binding_v1",
            "provider_id": "attachment_table_row_source_occurrence_provider_v1",
            "inventory_kind_alias": "attachment_table_row",
            "resource_kind": "attachment_table_row_occurrence",
            "normalized_field": "table.row.cell_value",
            "predicate": "source_occurrence_row_contains",
            "operator": "case_insensitive_exact",
            "filter_slot_policy": "combined_present_intersection_v1",
            "requester_user_id": session.requester_user_id,
            "workspace_id": session.workspace_id,
            "source_scope_ids": list(session.authorized_source_scope_ids),
            "authorized_scope_fingerprint": authorized_scope_fingerprint,
            "policy_id": _SOURCE_SCHEMA_CAPABILITY_POLICY_ID,
        }
    )
    if (
        set(manifest) != expected_keys
        or manifest.get("artifact_id")
        != _SOURCE_SCHEMA_CAPABILITY_MANIFEST_ARTIFACT_ID
        or manifest.get("schema_version") != 1
        or manifest.get("policy_id") != _SOURCE_SCHEMA_CAPABILITY_POLICY_ID
        or manifest.get("review_status") != "candidate_only_unreviewed"
        or manifest.get("human_review_complete") is not False
        or manifest.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or not _is_sha256(expected_byte_sha256)
        or any(not _is_sha256(manifest.get(key)) for key in fingerprint_fields)
        or manifest.get("workspace_fingerprint") != sha256_json(session.workspace_id)
        or manifest.get("retrieval_snapshot_byte_sha256")
        != safe_binding.get("retrieval_snapshot_byte_sha256")
        or manifest.get("retrieval_snapshot_fingerprint")
        != safe_binding.get("retrieval_snapshot_fingerprint")
        or manifest.get("source_snapshot_fingerprint")
        != safe_binding.get("source_snapshot_fingerprint")
        or manifest.get("source_session_binding_fingerprint")
        != session.source_session_binding_fingerprint
        or manifest.get("authorized_scope_fingerprint")
        != authorized_scope_fingerprint
        or manifest.get("provider_binding_fingerprint")
        != provider_binding_fingerprint
        or manifest.get("tokenizer_profile_fingerprint")
        != tokenizer_profile.profile_fingerprint
        or not isinstance(columns, list)
        or not columns
    ):
        raise ContractValidationError(
            "production source schema capability manifest binding is invalid"
        )
    mapping: dict[str, frozenset[str]] = {}
    for item in columns:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"column_hash", "candidate_hashes"}
            or not _is_sha256(item.get("column_hash"))
            or not isinstance(item.get("candidate_hashes"), list)
            or not item["candidate_hashes"]
            or item["candidate_hashes"] != sorted(set(item["candidate_hashes"]))
            or any(not _is_sha256(value) for value in item["candidate_hashes"])
            or item["column_hash"] in mapping
        ):
            raise ContractValidationError(
                "production source schema capability manifest is invalid"
            )
        mapping[str(item["column_hash"])] = frozenset(item["candidate_hashes"])
    ordered_mapping = [
        [column_hash, sorted(mapping[column_hash])]
        for column_hash in sorted(mapping)
    ]
    manifest_without_fingerprint = dict(manifest)
    manifest_without_fingerprint.pop("manifest_fingerprint", None)
    if (
        columns
        != [
            {
                "column_hash": column_hash,
                "candidate_hashes": sorted(mapping[column_hash]),
            }
            for column_hash in sorted(mapping)
        ]
        or manifest.get("column_count") != len(mapping)
        or manifest.get("candidate_hash_count")
        != len({value for values in mapping.values() for value in values})
        or manifest.get("mapping_fingerprint") != sha256_json(ordered_mapping)
        or manifest.get("manifest_fingerprint")
        != sha256_json(manifest_without_fingerprint)
    ):
        raise ContractValidationError(
            "production source schema capability manifest seal mismatch"
        )
    return mapping


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == len("sha256:") + 64
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _table_row_key(observation: Observation) -> tuple[Any, ...]:
    return (
        observation.asset_id,
        observation.location.get("sheet_name"),
        observation.location.get("table_index"),
        observation.location.get("row_index"),
    )

def _contains_tenant_id(value: Any) -> bool:
    if isinstance(value, Mapping):
        return "tenant_id" in value or any(_contains_tenant_id(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_tenant_id(item) for item in value)
    return False


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
    safe_binding = _validated_owner_safe_binding(
        loaded.safe_binding,
        source_session_binding_fingerprint=(
            loaded.session.source_session_binding_fingerprint
        ),
    )
    diagnostic_lineage_precompute = dict(
        safe_binding["lineage_crosswalk_precompute"]
    )
    diagnostic_lineage_precompute.pop(
        "source_session_binding_fingerprint",
        None,
    )
    return build_issue56_sealed_source_diagnostic_input(
        session=loaded.session,
        effective_graph_view=loaded.effective_graph_view,
        allowed_relation_types=relation_types,
        source_asset_fingerprint=str(safe_binding["source_asset_fingerprint"]),
        loader_contract_fingerprint=loader_contract_fingerprint,
        graph_revision_fingerprint=str(safe_binding["graph_revision_fingerprint"]),
        source_loader_binding_fingerprint=str(safe_binding["binding_fingerprint"]),
        lineage_crosswalk_precompute=diagnostic_lineage_precompute,
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


def _validated_owner_safe_binding(
    raw: Mapping[str, Any],
    *,
    source_session_binding_fingerprint: str | None,
) -> dict[str, Any]:
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
    expected_cache_key_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_issue56_evidence_identity_lineage_cache_key_v1",
            "index_fingerprint": binding.get("index_fingerprint"),
            "graph_revision_fingerprint": binding.get("graph_revision_fingerprint"),
            "source_session_binding_fingerprint": (
                source_session_binding_fingerprint
            ),
        }
    )
    if (
        binding.get("status") != "passed"
        or binding.get("identity_scope_mode_status") != IDENTITY_SCOPE_MODE
        or binding.get("tenant_dimension_status") != "not_modeled_not_fabricated"
        or not isinstance(precompute, Mapping)
        or not isinstance(counts, Mapping)
        or precompute.get("index_fingerprint") != binding.get("index_fingerprint")
        or precompute.get("graph_revision_fingerprint") != binding.get("graph_revision_fingerprint")
        or precompute.get("source_session_binding_fingerprint")
        != source_session_binding_fingerprint
        or precompute.get("cache_key_fingerprint")
        != expected_cache_key_fingerprint
        or not isinstance(precompute.get("counts"), Mapping)
        or precompute["counts"].get("authorized_evidence_count")
        != counts.get("authorized_observation_count")
    ):
        raise ContractValidationError("sealed source owner precompute binding mismatch")
    if binding.get("supplemental_observation_partition_status") == "loaded":
        if dict(relation_precompute or {}) != {
            "status": "skipped",
            "reason": "supplemental_observation_partition_not_applicable",
            "helper_invocation_count": 0,
        }:
            raise ContractValidationError(
                "sealed source owner relation projection precompute binding mismatch"
            )
        return binding
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
