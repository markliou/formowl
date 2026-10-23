"""Environment-bound adapter for the Issue #56 sealed-source diagnostic.

The CLI resolves this module by ``module:function``.  Source loading remains in
``formowl_mail.issue56_sealed_source`` so the mail owner path never imports the
gateway contract.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from email.headerregistry import HeaderRegistry
import hashlib
import json
import os
from pathlib import Path
import re
import time
from types import MappingProxyType, SimpleNamespace
from typing import Any, Final
import unicodedata

from formowl_auth.security import normalize_verified_email
from formowl_core import load_issue56_target_mail_tokenizer_profile
from formowl_contract import (
    CandidateMention,
    ContractValidationError,
    Observation,
    redact_public_raw_references,
    sha256_json,
    stable_resource_contract_id,
    to_plain,
)
from formowl_mail import build_mail_evidence_query_handler
from formowl_mail.answer import build_authorized_candidate_table_lookup, interpret_authorized_candidate_table_query, render_governed_evidence_answer
from formowl_mail.exact import (
    AuthorizedSourceOccurrence,
    SourceOccurrenceProvider,
    execute_deterministic_source_occurrence_inventory,
    authorized_source_occurrence_scope_fingerprint,
    source_occurrence_column_capability_hash,
    source_occurrence_exact_cell_value_hash,
    source_occurrence_projection_capability_hash,
    normalize_source_occurrence_structured_surface,
)
from formowl_mail.issue56_sealed_source import (
    reviewed_header_binding_key,
    APPROVER_ACTOR,
    ARTIFACT_ID as SEALED_SOURCE_LOAD_ARTIFACT_ID,
    IDENTITY_SCOPE_MODE,
    SOURCE_GRAPH_POLICY_ID,
    WORKSPACE_ID,
    _authorized_mail_selector_for_asset,
    _attachment_mail_parent_link,
    _validate_attachment_mail_parent,
    Issue56IngestionRevision,
    load_issue56_sealed_source,
)
from formowl_mail.hybrid import (
    AdaptiveQueryPlanner,
    _semantic_session_source_families,
    _is_attachment_text_observation,
    attach_authorized_source_occurrence_providers,
    execute_bounded_adaptive_query,
    _partition_structured_source_occurrence_table_query,
    _SOURCE_OCCURRENCE_STRUCTURED_TABLE_QUERY_POLICY_ID,
)
from formowl_mail.query import (
    MailAttachmentChildOccurrenceLineage,
    MailInlineTableOccurrenceLineage,
    MailEvidenceQueryResult,
    MailMessageOccurrenceLineage,
    RevisionOwnedMailSourceScan,
    TextDocumentOccurrenceLineage,
    REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES,
    _source_mail_observation_match,
    bind_typed_identifier_to_source_schema,
    _attachment_child_lineages,
    _safe_snippet,
    _citation_for_snippet,
    build_revision_owned_mail_evidence_query_handler,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from formowl_mail.semantic_plan import (
    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
    SEMANTIC_CLAIM_STRENGTH_BY_CLASS,
    SEMANTIC_QUERY_CLASSES,
    SemanticQueryPlan,
    authorized_permission_scope_matches,
    deterministic_query_class,
    validate_semantic_request_contract,
)
from formowl_retrieval.gateway import (
    _SOURCE_PHASE_TRACE, _trace, _source_trace_phase,
    _SOURCE_EVIDENCE_DEADLINE, _SOURCE_TERM_PLACEMENT, _SOURCE_OCCURRENCE_PAIR,
    _SourceEvidenceDeadlineExceeded,
    source_evidence_query_terms_scope,
    SOURCE_EVIDENCE_OBSERVATION_LIMIT,
    SOURCE_EVIDENCE_TIME_BUDGET_MS,
    check_source_evidence_deadline,
    source_evidence_supported_requested_fields,
    source_evidence_double_check,
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


# Part identifiers are labelled differently across the authorized mail tables.
# Keep the exact lookup bounded to source-declared identifier columns while
# accepting the common English and Chinese labels used by the production
# spreadsheets and embedded tables.  The native row still verifies the
# identifier before any evidence is projected.
_PART_IDENTIFIER_FIELD_ALIASES = frozenset(
    {
        "customer pn",
        "customer p/n",
        "customer part number",
        "customer part no",
        "customer part no.",
        "料號",
        "料号",
        "part number",
        "part no",
        "part no.",
        "part #",
        "part#",
        "p/n",
        "pn",
        "mpn",
        "material number",
        "material no",
        "material no.",
        "item number",
        "item no",
        "item no.",
    }
)


def _part_identifier_schema_fields(schema_fields: Sequence[str]) -> tuple[str, ...]:
    """Return source-declared columns that can contain a part identifier."""
    return tuple(
        field
        for field in schema_fields
        if normalize_source_occurrence_structured_surface(field)
        in _PART_IDENTIFIER_FIELD_ALIASES
    )


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


def _validate_production_session_lineages(session: Any) -> None:
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


class _KeyedIngestionLookup(Mapping):
    """Query-local reads only; accidental corpus iteration fails closed."""

    def __init__(self, getter: Callable[[str], Any]) -> None:
        self._getter = getter

    def __getitem__(self, key: str) -> Any:
        value = self._getter(key)
        if value is None:
            raise KeyError(key)
        return value

    def __iter__(self):
        raise ContractValidationError("indexed evidence requires keyed lookup")

    def __len__(self):
        raise ContractValidationError("indexed evidence enumeration is unavailable")


class _LoadedSealedSourceRecords:
    """Bounded reader over the already-loaded, permission-filtered snapshot."""

    def __init__(self, loaded: Any) -> None:
        observations = getattr(loaded, "observations", None)
        session = getattr(loaded, "session", None)
        query_bundle = getattr(loaded, "query_bundle", None)
        selector = getattr(
            getattr(query_bundle, "mail_import_session", None),
            "mail_import_session_id",
            None,
        )
        if (
            not isinstance(observations, tuple)
            or any(not isinstance(item, Observation) for item in observations)
            or session is None
            or not isinstance(selector, str)
            or not selector.strip()
        ):
            raise ContractValidationError("sealed source fallback binding is unavailable")
        self._observations = observations
        self._session = session
        self.authorized_mail_import_session_ids = (selector,)

    def scan_authorized_observations(
        self,
        *,
        source_family: str,
        max_observations: int,
        deadline_monotonic: float | None = None,
        source_scope_ids: Sequence[str] = (),
        mail_import_session_id: str | None = None,
        observation_callback: Callable[[Observation, str], bool] | None = None,
    ) -> RevisionOwnedMailSourceScan:
        if source_family not in {"mail", "document_text"}:
            raise ContractValidationError("source fallback family is invalid")
        if (
            isinstance(max_observations, bool)
            or not isinstance(max_observations, int)
            or max_observations < 1
        ):
            raise ContractValidationError("source fallback observation limit is invalid")
        authorized_source = getattr(self._session, "authorized_source", None)
        if authorized_source is None:
            raise ContractValidationError("sealed source fallback authority is unavailable")
        expected_scopes = tuple(sorted(set(authorized_source.source_scope_ids)))
        if source_family == "document_text":
            if (
                tuple(source_scope_ids) != expected_scopes
                or not source_scope_ids
                or mail_import_session_id is not None
            ):
                raise ContractValidationError("source fallback document scope is invalid")
        elif source_scope_ids or mail_import_session_id != self.authorized_mail_import_session_ids[0]:
            raise ContractValidationError("source fallback mail scope is invalid")
        selected: list[tuple[Observation, str]] = []
        scanned = 0
        for observation in self._observations:
            if (
                deadline_monotonic is not None
                and time.monotonic() >= deadline_monotonic
            ):
                return RevisionOwnedMailSourceScan(
                    tuple(selected), scanned, False, "deadline",
                )
            scope_id = to_plain(observation.permission_scope).get("scope_id")
            if source_family == "document_text":
                if (
                    observation.modality != "text"
                    or observation.observation_type not in {"heading", "paragraph"}
                    or not isinstance(scope_id, str)
                    or scope_id not in source_scope_ids
                    or not authorized_permission_scope_matches(
                        observation.permission_scope,
                        authorized_source=authorized_source,
                        source_kind=AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
                    )
                ):
                    continue
                source_scope = scope_id
            else:
                if (
                    observation.modality != "mail"
                    or observation.observation_type
                    not in REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES
                    or not authorized_permission_scope_matches(
                        observation.permission_scope,
                        authorized_source=authorized_source,
                        source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                    )
                ):
                    continue
                source_scope = self.authorized_mail_import_session_ids[0]
            if scanned >= max_observations:
                return RevisionOwnedMailSourceScan(
                    tuple(selected), scanned, False, "observation_limit",
                )
            scanned += 1
            if observation_callback is None:
                selected.append((observation, source_scope))
            elif not observation_callback(observation, source_scope):
                return RevisionOwnedMailSourceScan((), scanned, False, "callback")
        if (
            deadline_monotonic is not None
            and time.monotonic() >= deadline_monotonic
        ):
            return RevisionOwnedMailSourceScan(
                tuple(selected), scanned, False, "deadline",
            )
        return RevisionOwnedMailSourceScan(tuple(selected), scanned, True)


_GRAPH_SOURCE_RECOVERY_MISS_STATUSES = frozenset(
    {"not_found", "no_answer", "incomplete", "partial", "pending_review"}
)


def _graph_source_recovery_is_eligible(
    *,
    arguments: Mapping[str, Any],
    request_query_class: Any,
    result: Any,
    request_contract_summary: Mapping[str, Any] | None,
    query_agent_payload: Mapping[str, Any],
    requested_fields: Sequence[str] = (),
    supported_requested_fields: Sequence[str] = (),
) -> bool:
    """Allow recovery for a validated graph lookup miss without field proof."""

    subqueries = query_agent_payload.get("subqueries", ())
    result_fingerprint_bound = any(
        step.get("result_fingerprint") == getattr(result, "result_fingerprint", None)
        for step in subqueries
        if isinstance(step, Mapping)
    )
    parent_binding_fingerprint = (
        request_contract_summary.get("request_contract_fingerprint")
        if isinstance(request_contract_summary, Mapping)
        else None
    )
    parent_binding_bound = (
        getattr(result, "status", None) == "pending_review"
        and isinstance(getattr(result, "query_hash", None), str)
        and isinstance(getattr(result, "plan_fingerprint", None), str)
        and isinstance(parent_binding_fingerprint, str)
        and all(
            step.get("result_fingerprint") is None
            for step in subqueries
            if isinstance(step, Mapping)
        )
        and any(
            isinstance(step, Mapping)
            and step.get("query_hash") == result.query_hash
            and step.get("plan_fingerprint") == result.plan_fingerprint
            and step.get("request_contract_fingerprint")
            == parent_binding_fingerprint
            for step in subqueries
        )
    )
    field_coverage_miss = bool(requested_fields) and not supported_requested_fields
    eligible_statuses = _GRAPH_SOURCE_RECOVERY_MISS_STATUSES | (
        {"ok"} if field_coverage_miss else set()
    )
    citation_suppresses_recovery = bool(
        getattr(result, "answer_citation_hashes", ())
    ) and not field_coverage_miss
    return (
        request_query_class == getattr(result, "query_class", None) == "evidence_lookup"
        and getattr(result, "status", None) in eligible_statuses
        and not citation_suppresses_recovery
        and getattr(result, "exact_result", None) is None
        and not any(
            arguments.get(key) is not None
            for key in ("exact_inventory_kind", "exact_field", "cursor", "table_query")
        )
        and query_agent_payload.get("stop_reason") != "provider_error"
        and query_agent_payload.get("status")
        not in {"error", "failed", "permission_denied"}
        and isinstance(subqueries, (list, tuple))
        and bool(subqueries)
        and all(
            isinstance(step, Mapping)
            and str(step.get("validation_status", "")).startswith("validated_")
            and step.get("status") in eligible_statuses
            for step in subqueries
        )
        and (result_fingerprint_bound or parent_binding_bound)
    )


def _source_start_capabilities(revision: Issue56IngestionRevision) -> dict[str, Any]:
    source = revision.authorized_source
    if source is None or revision.source_records is None:
        raise ContractValidationError("source-start authority is unavailable")
    families = []
    if source.authorizes_source_kind(AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND):
        families.append("mail")
        if revision.exact_lookup_manifest.get("counts", {}).get("attachment_authorized_row", 0):
            families.append("attachment_table")
    if source.authorizes_source_kind(AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND):
        families.append("document_text")
    if not families:
        raise ContractValidationError("source-start source family is unavailable")
    core = {
        "artifact_id": "formowl_source_start_capability_summary_v1",
        "source_start": True,
        "workspace_id": revision.safe_binding.get("workspace_id", WORKSPACE_ID),
        "source_families": families,
        "projection_status": "unavailable",
        "source_revision_sha256": revision.safe_binding["source_revision_sha256"],
        "snapshot_sha256": revision.safe_binding["snapshot_sha256"],
        "source_authority_fingerprint": revision.safe_binding[
            "source_authority_fingerprint"
        ],
        "source_session_binding_fingerprint": revision.safe_binding[
            "source_session_binding_fingerprint"
        ],
        "query_classes": ["evidence_lookup"],
        "coverage_status": (
            "complete"
            if revision.safe_binding.get("extraction_coverage", {}).get(
                "source_completeness_certified"
            )
            is True
            else "incomplete"
        ),
    }
    lookup = _IngestionExactCellLookup(revision) if revision.exact_lookup_manifest else None
    fields = list(lookup.capability_fields) if lookup else []
    providers = list(lookup.capability_providers) if lookup else []
    # The legacy provider totals combine candidate and source-provided rows;
    # they are not verified per-column/per-structure counts for source-start.
    for item in fields:
        item["authorized_family_row_count"] = item.pop("authorized_occurrence_count")
        safe_field, redacted = redact_public_raw_references(item["field"])
        item["label_redacted"] = bool(redacted) or len(safe_field) > 120
        item["field"] = safe_field[:120]
    for item in providers:
        item.pop("source_provided_occurrence_count", None)
        item.pop("candidate_only_occurrence_count", None)
        item["coverage_status"] = "incomplete"
    # Usable native labels precede redacted native labels and other fields.
    # Retain manifest order within each class and all field safety flags.
    fields.sort(key=lambda item: (
        item["structure_status"] != "source_provided",
        item["structure_status"] == "source_provided" and item["label_redacted"],
    ))
    structured_supported = any(item["structure_status"] == "source_provided" and not item["label_redacted"] for item in fields)
    core.update({
        "projection_fields": fields[:128],
        "projection_field_count": len(fields),
        "returned_projection_field_count": min(len(fields), 128),
        "listing_status": "truncated" if len(fields) > 128 else "complete",
        "providers": providers,
        "query_contract": {
            "native_locator_kinds": ["attachment_page"] if "mail" in families else [],
            "structured_table_query_supported": structured_supported,
            "projection_labels_must_match_authorized_fields": True,
            "candidate_only_is_deterministic_exact": False,
            "complete_inventory_supported": False,
            "native_formula_recalculation_supported": False,
            "native_display_semantics_supported": False,
            "value_representation": "extracted_cell_text",
            "native_date_normalization_supported": False,
            "merged_header_inference_supported": False,
        },
    })
    if structured_supported:
        core["query_classes"].append("exact_set_or_inventory")
    if "mail" in families:
        selector_ids = getattr(revision.source_records, "authorized_mail_import_session_ids", ())
        if (
            not isinstance(selector_ids, Sequence)
            or isinstance(selector_ids, (str, bytes))
            or len(selector_ids) > 128
            or any(not isinstance(value, str) or not value.strip() for value in selector_ids)
            or len(set(selector_ids)) != len(selector_ids)
        ):
            raise ContractValidationError("mail source selector binding is invalid")
        core["selector_count"] = len(selector_ids)
        # Captured mail can have no owner-bound import selector. Omit the
        # optional binding so consumers retain fail-closed mail selection
        # while ordinary chat can proceed.
        if selector_ids:
            core.update({
                "mail_selector_kind": "mail_import_session_id",
                "authorized_mail_import_session_ids": list(selector_ids),
            })
    result = {**core, "capability_fingerprint": sha256_json(core)}
    validate_public_gateway_payload(result)
    return result


# Source-start UAT hydrates source records plus their governed parent context.
# This caller-owned budget does not change the shared 500ms recovery default,
# turn deadline, read/item/byte caps, source scope or completeness claims.
SOURCE_START_EVIDENCE_TIME_BUDGET_MS: Final[int] = 2_000


def _exact_column_applicable(revision: Any, item: Mapping[str, Any]) -> bool:
    """SPEC §7.5: source-provided or reviewed-header label-level exact column."""
    return item["structure_status"] == "source_provided" or (
        item["structure_status"] == "candidate_only"
        and item["column_hash"] in getattr(revision, "reviewed_header_column_hashes", frozenset())
    )


def _effective_cell_structure_status(revision: Any, cell: Observation, row_structure: Mapping[str, Any]) -> str:
    """Upgrade one candidate data-row cell only when its own table header is approved."""
    status = ((cell.payload or {}).get("table_structure") or {}).get("structure_status", "unavailable")
    approved = getattr(revision, "reviewed_header_bindings", frozenset())
    if (
        status == "candidate_only" and approved
        and row_structure.get("structure_status") == "candidate_only"
        and row_structure.get("row_role") == "data_candidate"
        and reviewed_header_binding_key(cell) in approved
    ):
        return "reviewed_header"
    return status


def _execute_source_start_table(
    revision: Issue56IngestionRevision, *, lookup: _IngestionExactCellLookup | None,
    arguments: Mapping[str, Any], request_contract: Mapping[str, Any],
    mail_tool: bool, selector: str | None, identifier_terms: tuple[str, ...],
    required_terms: tuple[str, ...] = (),
    automatic: bool = False, source_budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind source-native cells to the existing typed binder and exact executor.

    The source shortlist is deliberately incomplete even when every returned
    field is supported. No graph/index revision is manufactured or rebuilt.
    """
    source = revision.authorized_source
    limit = arguments.get("limit" if mail_tool else "page_size", 5 if mail_tool else 10)
    if type(limit) is not int or not 1 <= limit <= 128:
        raise ContractValidationError("source-start evidence limit is invalid")
    if arguments.get("cursor") is not None or arguments.get("exact_inventory_kind") is not None:
        raise ContractValidationError("source-start complete inventory is unavailable")
    deadline = time.monotonic() + SOURCE_START_EVIDENCE_TIME_BUDGET_MS / 1000
    if source_budget is not None:
        deadline = min(deadline, source_budget["deadline"])
    inherited_deadline = _SOURCE_EVIDENCE_DEADLINE.get()
    if inherited_deadline is not None:
        deadline = min(deadline, inherited_deadline)
    requested = tuple(request_contract["requested_fields"])
    table_query = arguments.get("table_query")
    families = tuple(request_contract["source_family_scope"])
    evidence_by_id: dict[str, dict[str, Any]] = {}
    native: dict[str, Observation] = {}

    def clarification() -> dict[str, Any]:
        payload = {
            "status": "clarification_required", "citations": [], "evidence": [],
            "deterministic_exact": False, "exact_result": None,
            "warnings": ["source_table_binding_requires_clarification"],
        }
        if mail_tool:
            payload.update(mail_import_session_id=selector, evidence_snippets=[])
        return payload

    if source is None or lookup is None or not set(families).intersection({"mail", "attachment_table"}):
        return clarification()
    fields = [item for item in lookup._columns
              if ("mail" if item["inline_table"] else "attachment_table") in families
              and _exact_column_applicable(revision, item)]
    available = {normalize_source_occurrence_structured_surface(item["field"]): item["field"] for item in fields}
    if table_query is not None:
        if (not isinstance(table_query, Mapping) or set(table_query) != {"filters", "projection_fields"}
                or not isinstance(table_query["filters"], list) or not 1 <= len(table_query["filters"]) <= 4
                or not isinstance(table_query["projection_fields"], list) or not 1 <= len(table_query["projection_fields"]) <= 8):
            raise ContractValidationError("source occurrence structured table query shape is invalid")
        labels = list(table_query["projection_fields"])
        for item in table_query["filters"]:
            if (not isinstance(item, Mapping) or set(item) != {"field", "value"}
                    or not isinstance(item["value"], str) or not item["value"].strip() or len(item["value"]) > 400):
                raise ContractValidationError("source occurrence structured table query filter is invalid")
            labels.append(item["field"])
    else:
        # Automatic evidence lookup may ask for a business field that the
        # current native table does not expose. Keep supported source labels
        # and disclose missing request fields instead of dropping the row.
        labels = [
            available[normalize_source_occurrence_structured_surface(field)]
            for field in requested
            if isinstance(field, str)
            and field.strip()
            and len(field) <= 120
            and normalize_source_occurrence_structured_surface(field) in available
        ]
    if (not labels or any(not isinstance(label, str) or not label.strip() or len(label) > 120
                          or normalize_source_occurrence_structured_surface(label) not in available for label in labels)):
        return clarification()
    normalized_projections = [normalize_source_occurrence_structured_surface(label)
                              for label in (table_query["projection_fields"] if table_query else labels)]
    if len(set(normalized_projections)) != len(normalized_projections):
        return clarification()
    if table_query and any(normalize_source_occurrence_structured_surface(field) not in normalized_projections for field in requested):
        return clarification()

    # A prefixed identifier may bind to a native numeric cell only when an
    # authorized source schema supplies the same type prefix in its field label.
    # The native value is kept exactly, including leading zeroes.  This is a
    # schema binding, never a general prefix-stripping alias.
    effective_required_terms = required_terms
    if identifier_terms:
        schema_fields = tuple(item["field"] for item in fields)
        typed_bindings = bind_typed_identifier_to_source_schema(
            identifier_terms[0], schema_fields,
        )
        normalized_binding_fields = {
            normalize_source_occurrence_structured_surface(field)
            for field, _ in typed_bindings
        }
        if len(normalized_binding_fields) > 1:
            return clarification()
        if typed_bindings:
            bound_field, bound_value = typed_bindings[0]
            bound_field_normalized = normalize_source_occurrence_structured_surface(bound_field)
            if table_query is None:
                table_query = {
                    "filters": [{"field": bound_field, "value": bound_value}],
                    "projection_fields": list(labels),
                }
                effective_required_terms = tuple(
                    term for term in required_terms
                    if normalize_source_occurrence_structured_surface(term)
                    != normalize_source_occurrence_structured_surface(identifier_terms[0])
                )
            else:
                matching_filters = [
                    item for item in table_query["filters"]
                    if normalize_source_occurrence_structured_surface(item["field"])
                    == bound_field_normalized
                    and normalize_source_occurrence_structured_surface(item["value"])
                    == normalize_source_occurrence_structured_surface(bound_value)
                ]
                if matching_filters:
                    effective_required_terms = tuple(
                        term for term in required_terms
                        if normalize_source_occurrence_structured_surface(term)
                        != normalize_source_occurrence_structured_surface(identifier_terms[0])
                    )

    def collect(group: tuple[Observation, ...]) -> None:
        native.update((item.observation_id, item) for item in group)

    scan = lookup.scan_source_rows(
        # The identifier selects the exact predicate, not permission to drop
        # other validated content constraints from the same native row.
        required_terms=(
            tuple(dict.fromkeys((*identifier_terms, *required_terms)))
            if table_query is None
            else effective_required_terms
        ),
        query_text=arguments["query_text"], source_families=families,
        mail_import_session_id=selector, max_observations=SOURCE_EVIDENCE_OBSERVATION_LIMIT,
        deadline_monotonic=deadline, evidence_by_id=evidence_by_id,
        observation_callback=lambda item, scope: len(evidence_by_id) < min(limit, 100),
        table_query=table_query, native_group_callback=collect,
    )
    evidence = list(evidence_by_id.values())
    if source_budget is not None:
        source_budget["reads"] += scan.scanned_observation_count
        source_budget["evidence"] += len(evidence)
        source_budget["context_bytes"] += sum(
            len(json.dumps(item, ensure_ascii=False).encode("utf-8")) for item in evidence
        )
    results = []
    binding_unresolved = False
    if native and time.monotonic() < deadline:
        hashes = tuple(sorted((key, sha256_json(item.to_dict())) for key, item in native.items()))
        lineages = normalized_authorized_observation_lineages(
            tuple(native.values()), authorized_source=source,
            occurrence_lineages=tuple(source_occurrence_lineage_from_observation(item, authorized_source=source)
                                     for item in native.values()
                                     if item.observation_type in {"email_message", "email_attachment_occurrence"}),
        )
        scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
            requester_user_id=arguments["requester_user_id"], workspace_id=arguments["workspace_id"],
            source_scope_ids=source.source_scope_ids, authorized_observation_hashes=hashes,
            source_session_binding_fingerprint=revision.safe_binding["source_session_binding_fingerprint"],
        )
        # This is only the established provider's input shape, never a runtime
        # semantic session, projection, graph or replacement store.
        provider_input = SimpleNamespace(
            authorized_observations=tuple(native.values()), authorized_observation_hashes=hashes,
            occurrence_lineages=lineages, requester_user_id=arguments["requester_user_id"],
            workspace_id=arguments["workspace_id"], authorized_source_scope_ids=source.source_scope_ids,
            index=SimpleNamespace(_runtime_components=SimpleNamespace(tokenizer_profile=lookup._tokenizer_profile)),
        )
        if table_query is None:
            matching_labels = {
                cell["field"] for item in evidence for cell in item["table_row"]["cells"]
                if cell["source_proven_field_schema"] and normalize_source_occurrence_structured_surface(cell["value"])
                == normalize_source_occurrence_structured_surface(identifier_terms[0])
            }
            if len(matching_labels) > 1:
                return clarification()
            present_fields = {
                normalize_source_occurrence_structured_surface(cell["field"])
                for item in evidence for cell in item["table_row"]["cells"]
                if cell["source_proven_field_schema"]
            }
            projections = [field for field in labels
                           if normalize_source_occurrence_structured_surface(field) in present_fields]
            if matching_labels and projections:
                table_query = {"filters": [{"field": next(iter(matching_labels)), "value": identifier_terms[0]}],
                               "projection_fields": projections}
                labels.append(table_query["filters"][0]["field"])
        for item in evidence:
            for label in labels:
                members = [cell for cell in item["table_row"]["cells"]
                           if normalize_source_occurrence_structured_surface(cell["field"]) == normalize_source_occurrence_structured_surface(label)]
                if len(members) > 1 or any(not cell["source_proven_field_schema"] for cell in members):
                    return clarification()
        for inline, family in ((False, "attachment_table"), (True, "mail")):
            if family not in families or table_query is None:
                continue
            if time.monotonic() >= deadline:
                break
            provider = _build_attachment_table_row_provider(provider_input, authorized_scope_fingerprint=scope_fingerprint, inline_tables=inline)
            if provider is None:
                continue
            # A query-keyed shortlist and a partial corpus cannot certify a set
            # or negative. Preserve that boundary inside the executor's contract.
            provider = replace(provider, source_asset_reason_counts=(("unresolved", 1),))
            try:
                partition, _, _ = _partition_structured_source_occurrence_table_query(provider=provider, table_query=table_query)
            except ContractValidationError as exc:
                binding_unresolved = binding_unresolved or not (automatic and str(exc).endswith("is unavailable"))
                continue
            plan = SemanticQueryPlan(
                query_hash=sha256_json(arguments["query_text"]), query_class="exact_set_or_inventory",
                source_kind=source.source_kind, source_scope_ids=source.source_scope_ids,
                workspace_id=arguments["workspace_id"], requester_user_id=arguments["requester_user_id"],
                required_permissions=("read",), user_graph_revision_id="unavailable",
                canonical_graph_revision_id="unavailable", ontology_revision_id="unavailable",
                assembly_policy_id="source_start", allowed_paths=(), seed_node_ids=(), max_hops=0,
                max_fanout=0, candidate_limit=0, result_limit=min(limit, 100), evidence_budget=128,
                time_budget_ms=SOURCE_EVIDENCE_TIME_BUDGET_MS, repair_budget=0, repair_attempt_count=0,
                claim_strength="cited_evidence", exact_operation="inventory_with_count",
                exact_inventory_kind=provider.resource_kind, exact_normalized_field=provider.normalized_field,
                exact_predicate=provider.predicate, exact_operator=provider.operator,
                exact_source_occurrence_provider_fingerprint=provider.provider_fingerprint,
                exact_filter_term_hashes=partition.filter_term_hashes,
                exact_topic_term_hashes=partition.filter_term_hashes,
                exact_projection_term_hashes=partition.projection_column_hashes,
                exact_column_value_hash_pairs=partition.column_value_hash_pairs,
                exact_lexical_term_ledger=partition.lexical_term_ledger,
                exact_grammar_policy_fingerprint=sha256_json([
                    _SOURCE_OCCURRENCE_STRUCTURED_TABLE_QUERY_POLICY_ID,
                    provider.provider_fingerprint, partition.column_value_hash_pairs,
                    partition.projection_column_hashes,
                ]),
            )
            if time.monotonic() >= deadline:
                break
            results.append(execute_deterministic_source_occurrence_inventory(
                plan=plan, provider=provider, expected_authorized_scope_fingerprint=scope_fingerprint,
                page_size=min(limit, 100), cursor=None,
            ))
    if binding_unresolved or len(results) > 1:
        return clarification()
    cited = {value for result in results for item in result.items for value in item.cited_observation_hashes}
    evidence = [item for item in evidence if item["citation_hash"] in cited]
    exact_result = results[0] if len(results) == 1 else None
    supported = source_evidence_supported_requested_fields(
        requested, exact_result=exact_result,
        answer_citation_hashes=tuple(sorted(cited)),
        verified_citation_lineages=tuple(pair for result in results for item in result.items for pair in item.governed_references),
    )
    missing = [field for field in requested if field not in supported]
    status = "partial" if evidence else "pending_review"
    coverage = {"status": "incomplete", "absence_claim": False, "scope": "declared_completed_ingestion_jobs",
                "reason": scan.stop_reason or "source_table_shortlist"}
    field_coverage = {
        "request_contract_fingerprint": sha256_json(request_contract),
        "requested_fields": list(requested), "supported_fields": list(supported),
        "missing_fields": missing, "status": "incomplete" if missing else "verified", "absence_claim": False,
        "evidence_citation_hashes": sorted(item["citation_hash"] for item in evidence),
    }
    field_coverage["coverage_fingerprint"] = sha256_json(field_coverage)
    payload = {
        "status": status, "evidence": evidence, "citations": [item["citation_hash"] for item in evidence],
        "deterministic_exact": bool(results), "exact_result": exact_result.to_safe_dict() if exact_result else None,
        "canonical_kg": False, "graph_hits": {"count": 0}, "coverage": coverage,
        "requested_field_coverage": field_coverage,
        "warnings": ["source_table_shortlist_incomplete", "native_value_semantics_contract_bound"],
        "query_agent": {"status": "pending_review", "stop_reason": "retrieval_projection_unavailable",
                        "original_query_hash": request_contract["original_query_hash"], "request_contract": dict(request_contract),
                        "context_bundle": {"citation_hashes": [item["citation_hash"] for item in evidence],
                                           "missing_field_hashes": [sha256_json(field) for field in missing]}},
    }
    if mail_tool:
        payload.update(mail_import_session_id=selector, query_hash=sha256_json(arguments["query_text"]),
                       evidence_snippets=evidence, citations=[_citation_for_snippet(item) for item in evidence])
    else:
        payload["answer"] = {"status": status, "text": "Source-backed table values are available; corpus coverage is incomplete." if evidence else "",
                             "answer_hash": sha256_json(payload), "citation_count": len(evidence)}
    validate_public_gateway_payload(payload)
    return payload


def _request_term_placement(arguments, *, mail_tool=False):
    binding = _SOURCE_TERM_PLACEMENT.get()
    if binding is None:
        return None  # Public callers retain the strict legacy AND.
    from formowl_mail.human_uat_orchestrator import _RequiredTermPlacement

    placement, wire_hash = binding
    contract = arguments.get("request_contract")
    public_arguments = {key: value for key, value in arguments.items()
                        if key not in {"requester_user_id", "workspace_id", "session_id"}}
    terms = arguments.get("required_terms")
    if (not isinstance(placement, _RequiredTermPlacement)
            or sha256_json({"name": "query_mail_evidence" if mail_tool else "query_effective_graph_view",
                            "arguments": public_arguments}) != wire_hash
            or not isinstance(contract, Mapping)
            or contract.get("original_query_hash") != placement.original_query_hash
            or sha256_json(contract) != placement.request_contract_fingerprint
            or contract.get("query_class") != "evidence_lookup"
            or contract.get("source_family_scope") != ["mail"]
            or not isinstance(terms, list)
            or tuple(sorted(unicodedata.normalize("NFKC", term.strip()).casefold()
                            for term in terms if isinstance(term, str))) != placement.required_terms
            or not placement.child_terms or placement.context_term not in placement.required_terms
            or placement.surface not in {"mail_occurrence_context", "mail_subject"}
            or placement.predicate not in {"literal_contains", "normalized_literal_equals"}
            or (placement.predicate == "normalized_literal_equals" and placement.surface != "mail_subject")
            or any(arguments.get(key) is not None for key in (
                "table_query", "exact_inventory_kind", "exact_field", "cursor",
            ))):
        raise ContractValidationError("source occurrence placement request binding is invalid")
    return placement


def _placement_initial_context(query_agent):
    """Withhold unproved content, retaining execution/coverage diagnostics."""
    context = dict(query_agent["context_bundle"])
    context.update(citation_hashes=[], lineage_fingerprints=[], successful_subqueries=[
        {**entry, "evidence": [], "exact_items": []}
        for entry in context.get("successful_subqueries", ())
    ])
    context.pop("bundle_fingerprint", None)
    context["bundle_fingerprint"] = sha256_json(context)
    return {**query_agent, "context_bundle": context,
            "warnings": list(dict.fromkeys((*query_agent.get("warnings", ()), "occurrence_placement_unverified")))}


def _placement_mail_group(placement, observation, scope_id, item, *, source, protected_terms, tokenizer):
    """All predicates on one guarded pair and the actual visible projection."""
    pair = _SOURCE_OCCURRENCE_PAIR.get()
    if pair is None or pair[0] is not observation:
        return None
    _, parent, full_key = pair
    if (observation.observation_type != "email_body_segment" or observation.modality != "mail"
            or _attachment_mail_parent_link(observation) is not None
            or full_key[1:] != (observation.extractor_run_id, observation.asset_id,
                               scope_id, observation.location.get("message_occurrence_id"))):
        return None
    # Reuse the existing provenance, permission, fingerprint and whole-pair
    # projection boundary. The job component is supplied only by guarded reader.
    grouped = _mail_header_context(observation, item, parent, source=source, scope_id=scope_id)
    header = grouped.get("_mail_parent_header")
    if not isinstance(header, Mapping) or grouped.get("content_redacted") or header.get("content_redacted"):
        return None
    def normalize(value):
        return unicodedata.normalize("NFKC", value).casefold()
    body = observation.text or ""
    if not all(term in normalize(body) and term in normalize(grouped.get("snippet", ""))
               for term in placement.child_terms):
        return None
    context_identifiers = {span.exact_token for span in tokenizer.analyze(placement.context_term).protected_identifiers}
    child_identifiers = {span.exact_token for span in tokenizer.analyze(" ".join(placement.child_terms)).protected_identifiers}
    if not ((protected_terms - context_identifiers) | child_identifiers).issubset(
        set(tokenizer.analyze(body).tokens)
    ):
        return None
    fields = [value for key in ("subject", "sent_at")
              if isinstance(value := (parent.payload or {}).get(key), str)]
    if placement.surface == "mail_subject":
        fields = [(parent.payload or {}).get("subject", "")]
    else:
        fields.append(body)
    term = placement.context_term
    matches = any((normalize(value) == term if placement.predicate == "normalized_literal_equals"
                   else term in normalize(value)) for value in fields if isinstance(value, str))
    if not matches or not any(term in normalize(value) for value in (
        grouped.get("snippet", ""), header.get("snippet", ""),
    )):
        return None
    return grouped


def _closed_placement_mail_handler(handler):
    # Legacy mail bundle/revision paths cannot attest the new private pair.
    def guarded(arguments):
        if "native_locator" in (arguments.get("request_contract") or {}):
            raise ContractValidationError("native attachment page requires source-start handler")
        placement = _request_term_placement(arguments, mail_tool=True)
        result = handler(arguments)  # Existing validation/errors keep precedence.
        if placement is None:
            return result
        result = {**result, "evidence_snippets": [], "citations": [],
                  "warnings": list(dict.fromkeys((*result.get("warnings", ()), "occurrence_placement_unverified")))}
        if "evidence" in result:
            result["evidence"] = []
        if result.get("status") not in {"error", "failed", "permission_denied"}:
            result["status"] = "pending_review"
        if isinstance(result.get("query_agent"), Mapping):
            result["query_agent"] = _placement_initial_context(result["query_agent"])
        coverage = result.get("requested_field_coverage")
        if isinstance(coverage, Mapping):
            coverage = {**coverage, "supported_fields": [], "missing_fields": coverage["requested_fields"],
                        "evidence_citation_hashes": [], "status": "incomplete", "absence_claim": False}
            coverage.pop("coverage_fingerprint", None)
            coverage["coverage_fingerprint"] = sha256_json(coverage)
            result["requested_field_coverage"] = coverage
        return result
    guarded.__dict__.update(handler.__dict__)
    return guarded


def _mail_header_context(observation, item, parent, *, source, scope_id, attachment_parent=None):
    """Project already-read outer headers, never infer them from quoted bodies."""
    attachment_context = {}
    if attachment_parent is not None:
        # Validate child -> attachment separately from attachment -> outer mail.
        # Child document asset/run coordinates are deliberately not mail keys.
        _attachment_child_lineages({
            observation.observation_id: observation,
            attachment_parent.observation_id: attachment_parent,
        })[observation.observation_id]
        attachment_context = {
            "parent_attachment_observation_id": attachment_parent.observation_id,
            "parent_attachment_observation_hash": sha256_json(attachment_parent.to_dict()),
        }
        item = {**item, "source_context": {
            "relationship": "attachment_parent", **attachment_context,
            "outer_header_status": "not_present_in_current_context",
        }}
        observation = attachment_parent
    else:
        if observation.observation_type != "email_body_segment":
            return item
        item = {**item, "snippet": "[mail body; quoted headers are not outer message headers] " + item["snippet"]}
    if parent is None:
        return item
    explicit_link = _attachment_mail_parent_link(observation)
    if explicit_link is not None:
        _validate_attachment_mail_parent(observation, parent)
    if (
        parent.observation_type != "email_message" or parent.modality != "mail"
        or parent.asset_id != observation.asset_id
        or parent.extractor_run_id != (
            explicit_link["parent_extractor_run_id"] if explicit_link else observation.extractor_run_id
        )
        or parent.location.get("message_occurrence_id") != observation.location.get("message_occurrence_id")
        or to_plain(parent.permission_scope) != to_plain(observation.permission_scope)
        or not authorized_permission_scope_matches(
            parent.permission_scope, authorized_source=source,
            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
        )
        or not isinstance((parent.payload or {}).get("message_fingerprint"), str)
        or (observation.payload or {}).get("message_fingerprint") not in {
            None, parent.payload["message_fingerprint"],
        }
    ):
        raise ContractValidationError("mail outer header parent binding is invalid")
    fields = {key: value for key in ("subject", "sent_at")
              if isinstance(value := (parent.payload or {}).get(key), str) and value.strip()}
    if not fields:
        return item
    parent_hash = sha256_json(parent.to_dict())
    lineage = source_occurrence_lineage_from_observation(parent, authorized_source=source)
    header = {
        **{key: item[key] for key in ("email_message_id", "message_occurrence_id",
                                    "mail_import_session_id", "revision_binding") if key in item},
        "source_type": "mail_message", "source_observation_id": parent.observation_id,
        "message_occurrence_id": parent.location["message_occurrence_id"],
        "email_message_id": stable_resource_contract_id(
            "emailmsg", "EmailMessage", {"message_fingerprint": parent.payload["message_fingerprint"]},
        ),
        "citation_hash": parent_hash, "source_observation_hash": parent_hash,
        "occurrence_lineage_fingerprint": lineage.lineage_fingerprint,
        "source_scope_fingerprint": sha256_json(scope_id),
        "snippet": "[outer message headers; same occurrence]\n" + "\n".join(
            f"{key}: {value}" for key, value in fields.items()
        ),
        "source_context": {"relationship": "outer_message_header",
                           "anchor_citation_hash": item["citation_hash"], **attachment_context},
    }
    if attachment_context:
        item = {**item, "source_context": {**item["source_context"], "outer_header_status": "present"}}
    # This private staging member is expanded only with its admitted body. Both
    # source records retain their own hashes and consume the existing item cap.
    return {**item, "_mail_parent_header": _safe_snippet(header)}


def _bounded_mail_header_groups(items, *, limit, byte_limit=16 * 1024):
    if not any("_mail_parent_header" in item for item in items):
        return list(items), False
    evidence, seen, truncated = [], set(), False
    for item in items:
        body = {key: value for key, value in item.items() if key != "_mail_parent_header"}
        header = item.get("_mail_parent_header")
        if header is not None:
            body["mail_header_citation_hash"] = header["citation_hash"]
        group = [body] + ([header] if header is not None else [])
        group = [record for record in group if record["citation_hash"] not in seen]
        candidate = [
            header if header is not None and record["citation_hash"] == header["citation_hash"] else record
            for record in evidence
        ] + group
        if len(candidate) > limit or len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > byte_limit:
            truncated = True
            continue
        evidence = candidate
        seen.update(record["citation_hash"] for record in group)
    return evidence, truncated


def _ordinary_presentation_unit(item):
    """Only independent text and plain mail's own header; no native/neighbor chain."""
    context = item.get("source_context", {})
    if context.get("annotation_pin"):
        context = {key: value for key, value in context.items()
                   if key not in {"annotation_pin", "candidate_ids", "exact_field_proof"}}
    if context and (context.get("relationship") != "outer_message_header"
                    or any(key.startswith("parent_attachment") for key in context)):
        return False
    if (item.get("source_type") not in {"mail_body_segment", "mail_message", "mail_header"}
            and item.get("document_locator", {}).get("block_type") not in {"heading", "paragraph"}):
        return False
    header = item.get("_mail_parent_header")
    return not any(key in item for key in ("table_locator", "structured_values")) and (
        header is None or _ordinary_presentation_unit(header)
    )


def _soft_unit_utility(hits):
    # Field/token relevance is NOT validated field support.
    return len({field for field, _ in hits}), len(hits)


def _admit_source_model_envelope(payload, *, staged_items, limit, deadline, deferred_items=(),
                                 selection_hits=None, overflow_hashes=()):
    """Re-admit cached validated units against the unchanged complete presentation."""
    trace = _SOURCE_PHASE_TRACE.get()
    envelope_cell = _trace(trace, "phase", "envelope", before=len(payload.get("evidence_snippets", payload.get("evidence", ()))))

    def observed(result):
        _trace(envelope_cell, "finish", after=len(result.get("evidence_snippets", result.get("evidence", ()))))
        return result

    if deferred_items:
        agent = payload.get("query_agent", {})
        recovery = agent.get("context_bundle", {}).get("source_recovery", {})
        # Only the new cached suffix is gated here; no-cache compaction is legacy.
        # Invalid source/drain exceptions never return to this presentation path.
        for metadata in (payload, agent, recovery):
            if (metadata.get("status") in {"error", "failed", "permission_denied", "mcp_failed", "mcp_unavailable", "provider_unavailable"}
                    or any(metadata.get(key) not in (None, "") for key in ("failure_reason", "reason_code"))
                    or metadata.get("stop_reason") == "provider_error"):
                return observed(payload)
    if (payload.get("deterministic_exact") or payload.get("exact_result") is not None
            or "exact_inventory" in payload
            or payload.get("query_agent", {}).get("request_contract", {}).get("query_class") == "exact_set_or_inventory"
            or time.monotonic() >= deadline):
        return observed(payload)
    from formowl_mail.human_uat_orchestrator import compact_evidence_for_model, evidence_citation_ids

    content_key = "evidence_snippets" if "evidence_snippets" in payload else "evidence"

    def fits(value, diagnostic=None):
        records = value.get(content_key, ())
        citations = {item["citation_hash"] for item in records}
        required = {item["mail_header_citation_hash"] for item in records if item.get("mail_header_citation_hash")}
        required.update(item["source_context"]["anchor_citation_hash"] for item in records
                        if item.get("source_context", {}).get("anchor_citation_hash"))
        compact = compact_evidence_for_model(value, diagnostic=diagnostic)
        if len(records) > limit or not required.issubset(citations):
            return False
        return (set(evidence_citation_ids(compact)) == citations
                and (content_key != "evidence" or
                     Counter(json.dumps(item, sort_keys=True) for item in compact.get("evidence", ()))
                     == Counter(json.dumps(item, sort_keys=True) for item in records)))

    diagnostic = {}
    payload_fits = fits(payload, diagnostic)
    overflow = set(overflow_hashes)
    reselect = bool(overflow and selection_hits
                    and all(item["citation_hash"] in selection_hits for item in (*staged_items, *deferred_items))
                    and all(
        _ordinary_presentation_unit(item)
        for item in (*staged_items, *deferred_items, *payload.get(content_key, ()))
    ))
    # Overflow-only units must never slip into the legacy append-only suffix.
    cached_candidates = deferred_items
    deferred_items = tuple(item for item in deferred_items if item["citation_hash"] not in overflow)
    if payload_fits and not deferred_items and not reselect:
        return observed(payload)
    # Selection repairs only a proved full-envelope byte loss, not existing
    # representation filtering or a harmless regrouping of unchanged records.
    byte_loss = bool(diagnostic.get("reason_counts", {}).get("group_byte_budget"))
    if not payload_fits and not byte_loss:
        return observed(payload)

    def compose(evidence, *, truncated=True):
        # Copy only containers we update; immutable evidence/provenance and
        # unknown coverage metadata are neither recopied nor modified.
        result = dict(payload)
        result[content_key] = evidence
        citations = sorted(item["citation_hash"] for item in evidence)
        lineages = sorted(item["occurrence_lineage_fingerprint"] for item in evidence)
        result["citations"] = ([_citation_for_snippet(item) for item in evidence]
                               if content_key == "evidence_snippets" else citations)
        result["status"] = "partial" if evidence else "pending_review"
        if truncated:
            result["presentation_truncated"] = True
        if truncated and "warnings" in result:
            result["warnings"] = sorted(set((*result["warnings"], "context_limit")))
        agent = dict(result.get("query_agent", {}))
        if "query_agent" in result:
            result["query_agent"] = agent
        contract = agent.get("request_contract", {})
        fields = contract.get("requested_fields", result.get("requested_field_coverage", {}).get("requested_fields", ()))
        supported = source_evidence_supported_requested_fields(
            fields, exact_result=None, answer_citation_hashes=tuple(citations),
            verified_citation_lineages=tuple((item["citation_hash"], item["occurrence_lineage_fingerprint"])
                                            for item in evidence),
        )
        missing = [field for field in fields if field not in supported]
        field_coverage = result.get("requested_field_coverage")
        if isinstance(field_coverage, dict):
            field_coverage = result["requested_field_coverage"] = dict(field_coverage)
            field_coverage.update(supported_fields=list(supported), missing_fields=missing,
                                  evidence_citation_hashes=citations,
                                  status="incomplete" if missing else "verified")
            field_coverage.pop("coverage_fingerprint", None)
            field_coverage["coverage_fingerprint"] = sha256_json(field_coverage)
        context = agent.get("context_bundle")
        if isinstance(context, dict):
            context = agent["context_bundle"] = dict(context)
            if truncated:
                agent["warnings"] = sorted(set((*agent.get("warnings", ()), "context_limit")))
            context.update(citation_hashes=citations, lineage_fingerprints=lineages,
                           missing_field_hashes=[sha256_json(field) for field in missing])
            recovery = context.get("source_recovery")
            if isinstance(recovery, dict):
                recovery = context["source_recovery"] = dict(recovery)
                recovery.update(evidence=evidence, citation_hashes=citations,
                                lineage_fingerprints=lineages)
                if truncated:
                    recovery["warnings"] = sorted(set((*recovery.get("warnings", ()), "context_limit")))
                recovery.pop("recovery_fingerprint", None)
                recovery["recovery_fingerprint"] = sha256_json(recovery)
            context.pop("bundle_fingerprint", None)
            context["bundle_fingerprint"] = sha256_json(context)
            if isinstance(result.get("answer"), dict):
                result["answer"] = dict(result["answer"])
                result["answer"].update(status=result["status"], citation_count=len(citations),
                                        answer_hash=sha256_json(recovery))
                if not evidence:
                    result["answer"]["text"] = ""
        if "redaction_counts" in result:
            result["redaction_counts"] = dict(result["redaction_counts"])
            result["redaction_counts"]["redacted_value_count"] = sum(
                item.get("content_redacted") is True for item in evidence
            )
        return result

    selected = payload
    if not payload_fits:
        admitted = []
        selected = compose([])
        # Every trial includes the real final limitation metadata. A later rejection
        # cannot grow that metadata and evict an earlier accepted complete unit.
        # Staging has the existing 128-item source bound. Rejected candidates do
        # not consume published slots or prevent later independent units fitting.
        for item in staged_items[:128]:
            if time.monotonic() >= deadline:
                break
            records, truncated = _bounded_mail_header_groups([*admitted, item], limit=limit)
            if truncated:
                continue
            candidate = compose(records)
            accepted = fits(candidate)
            if time.monotonic() >= deadline:
                break
            if accepted:
                admitted.append(item)
                selected = candidate
    if reselect:
        pool, seen_candidates = [], set()
        for item in (*staged_items, *cached_candidates):
            if item["citation_hash"] not in seen_candidates and len(pool) < 128:
                pool.append(item)
                seen_candidates.add(item["citation_hash"])
        chosen, covered = [], set()
        proposal = compose([])
        while pool and time.monotonic() < deadline:
            # Stable max: staged order first, then stable reservoir order.
            best = max(range(len(pool)), key=lambda index: _soft_unit_utility(
                selection_hits.get(pool[index]["citation_hash"], set()) - covered,
            ))
            item = pool.pop(best)
            records, truncated = _bounded_mail_header_groups([*chosen, item], limit=limit)
            if truncated:
                continue
            trial = compose(records)
            if fits(trial) and time.monotonic() < deadline:
                chosen.append(item)
                covered.update(selection_hits.get(item["citation_hash"], ()))
                proposal = trial
        old_hits = set().union(*(selection_hits.get(item["citation_hash"], set())
                                for item in selected.get(content_key, ())))
        if time.monotonic() < deadline and _soft_unit_utility(covered) > _soft_unit_utility(old_hits):
            return observed(proposal)
    # Only the caller can supply same-turn, pre-deadline validated cache units.
    # This is final presentation, not a callback/replay or a new source budget.
    content = list(selected.get(content_key, ()))
    seen = {item["citation_hash"] for item in content}
    for item in deferred_items[:max(0, 128 - len(staged_items))]:
        if time.monotonic() >= deadline:
            break
        if item["citation_hash"] in seen:
            continue
        records, truncated = _bounded_mail_header_groups([*content, item], limit=limit)
        if truncated:
            continue
        candidate = compose(records, truncated=byte_loss)
        accepted = fits(candidate)
        if time.monotonic() >= deadline:
            break
        if accepted:
            content = records
            seen.update(record["citation_hash"] for record in records)
            selected = candidate
    return observed(selected)


def _select_reviewed_annotation_sources(revision, *, arguments, catalog, deadline):
    """Semantic nomination selects originals; identity and literals remain independent."""
    from formowl_mail.human_uat_orchestrator import validated_reviewed_annotation_selection
    if not arguments.get("reviewed_annotation_ids") and arguments.get("reviewed_annotation_pin") is None:
        return (), (), None
    if catalog is None:
        raise ContractValidationError("UAT reviewed annotation catalog is unavailable")
    original_text = None
    if len(revision.reviewed_source_annotations) > 128:
        from formowl_mail.issue56_sealed_source import (
            current_reviewed_annotation_query_binding, issue56_reviewed_annotation_catalog,
            reviewed_annotation_request_fingerprint,
        )
        binding = current_reviewed_annotation_query_binding()
        if (binding is None or binding.request_fingerprint != reviewed_annotation_request_fingerprint(arguments)):
            raise ContractValidationError("UAT reviewed annotation query view binding mismatch")
        check_source_evidence_deadline(deadline)
        catalog = issue56_reviewed_annotation_catalog(revision, user_text=binding.original_text)
        check_source_evidence_deadline(deadline)
        if catalog != json.loads(binding.catalog_json):
            raise ContractValidationError("UAT reviewed annotation query view is stale or changed")
        original_text = binding.original_text
        if arguments.get("request_contract", {}).get("original_query_hash") != catalog["original_query_hash"]:
            raise ContractValidationError("UAT reviewed annotation original query changed")
    target = validated_reviewed_annotation_selection(arguments, catalog=catalog, user_text=original_text)
    if (catalog["source_revision_sha256"] != revision.safe_binding["source_revision_sha256"]
            or catalog["reviewed_annotation_pin"] != revision.reviewed_annotation_pin):
        raise ContractValidationError("UAT reviewed annotation source pin mismatch")
    selected_ids = set(arguments["reviewed_annotation_ids"])
    # A model nomination is a hint, not an exclusive source filter.  When the
    # server has already bound the original query to one exact reviewed
    # identity, include every public catalog entry carrying that same identity.
    # This keeps annotation-guided selection additive and prevents provider
    # sampling from silently dropping a sibling row for the requested target.
    if (target is not None and catalog.get("view_mode") == "original_exact_identity_v1"
            and catalog.get("view_status") == "matched"):
        from formowl_mail.issue56_sealed_source import (
            _reviewed_identity_descriptors, _reviewed_identity_matches,
        )
        descriptors = _reviewed_identity_descriptors(catalog.get("entries", ()))
        selected_ids.update(
            annotation_id for annotation_id, identities in descriptors.items()
            if any(_reviewed_identity_matches(target, identity) for identity in identities)
        )
    matched = []
    for item in revision.reviewed_source_annotations:
        check_source_evidence_deadline(deadline)
        if item["candidate_atom_id"] in selected_ids:
            matched.append(item)
    hashes = tuple(dict.fromkeys(key for item in matched for key in item["source_hashes"]))
    if len(hashes) > 128:
        raise ContractValidationError("UAT reviewed annotation source selection exceeds bound")
    return tuple(item["candidate_atom_id"] for item in matched), hashes, target


def _reviewed_annotation_literals_match(observation, *, required_terms, target, protected_terms, tokenizer, deadline):
    """Only a validated identity is linked; genuine additional predicates stay literal."""
    check_source_evidence_deadline(deadline)
    terms = tuple(term for term in required_terms if term != target)
    protected = protected_terms - set(tokenizer.analyze(target).tokens)
    if observation.modality == "mail":
        # Empty tuple is an explicit vacuous AND, not the legacy no-term query.
        return _source_mail_observation_match(
            observation, query_terms=set(), required_terms=terms,
            protected_query_tokens=protected, tokenizer_profile=tokenizer,
            deadline_monotonic=deadline) is not None
    text = observation.text or observation.caption or ""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return (all(term in normalized for term in terms)
            and (not protected or protected.issubset(tokenizer.analyze(text).tokens)))


def _build_source_start_semantic_handler(
    revision: Issue56IngestionRevision,
    *,
    mail_tool: bool,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Run the shared source recheck directly over a pinned source snapshot."""
    source = revision.authorized_source
    records = revision.source_records
    if source is None or records is None:
        raise ContractValidationError("source-start composition binding is invalid")
    tokenizer = load_issue56_target_mail_tokenizer_profile()
    capabilities = _source_start_capabilities(revision)
    from formowl_mail.issue56_sealed_source import issue56_reviewed_annotation_catalog
    annotation_catalog = issue56_reviewed_annotation_catalog(revision)
    available_families = tuple(capabilities["source_families"])
    exact_lookup = (
        _IngestionExactCellLookup(revision) if revision.exact_lookup_manifest else None
    )
    selector_ids = tuple(getattr(records, "authorized_mail_import_session_ids", ()))
    coverage = revision.safe_binding.get("extraction_coverage", {})
    coverage_complete = (
        isinstance(coverage, Mapping)
        and coverage.get("source_completeness_certified") is True
        and not revision.safe_binding.get("bounded_canary_candidate_count")
    )

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        trace = _SOURCE_PHASE_TRACE.get()
        if not isinstance(arguments, Mapping):
            raise ContractValidationError("source-start arguments are invalid")
        required = {"query_text", "requester_user_id", "workspace_id", "session_id"}
        if not required <= set(arguments):
            raise ContractValidationError("source-start arguments are incomplete")
        if (
            arguments["requester_user_id"] != APPROVER_ACTOR
            or arguments["workspace_id"] != WORKSPACE_ID
            or not isinstance(arguments["session_id"], str)
            or not arguments["session_id"]
        ):
            return {
                "status": "permission_denied",
                "citations": [],
                "evidence": [],
                "warnings": ["source_start_actor_denied"],
            }
        query_text = arguments["query_text"]
        if not isinstance(query_text, str) or not query_text.strip():
            raise ContractValidationError("source-start query text is invalid")
        query_class = deterministic_query_class(query_text)
        if mail_tool:
            selector = arguments.get("mail_import_session_id")
            if selector not in selector_ids:
                return {
                    "status": "permission_denied",
                    "mail_import_session_id": selector,
                    "evidence_snippets": [],
                    "citations": [],
                    "warnings": ["mail_evidence_selector_denied"],
                }
            default_families = ["mail"]
            if request_contract := arguments.get("request_contract"):
                if (
                    not isinstance(request_contract, Mapping)
                    or request_contract.get("source_family_scope") != ["mail"]
                ):
                    raise ContractValidationError(
                        "mail source-start scope must remain mail-only"
                    )
        else:
            selector = None
            default_families = list(available_families)
        request_contract = arguments.get("request_contract")
        if request_contract is None:
            request_contract = {
                "original_query_hash": sha256_json(query_text),
                "query_class": query_class,
                "source_family_scope": default_families,
                "requested_fields": [],
                "maximum_claim_strength": SEMANTIC_CLAIM_STRENGTH_BY_CLASS[query_class],
            }
        request_contract = validate_semantic_request_contract(
            request_contract, available_source_families=available_families,
        )
        query_class = request_contract["query_class"]
        raw_terms = arguments.get("required_terms")
        if raw_terms is None:
            required_terms: tuple[str, ...] = ()
        elif (
            not isinstance(raw_terms, list)
            or not 1 <= len(raw_terms) <= 8
            or any(not isinstance(term, str) or not term.strip() or len(term) > 80 for term in raw_terms)
        ):
            raise ContractValidationError("source-start required terms are invalid")
        else:
            required_terms = tuple(sorted(
                unicodedata.normalize("NFKC", term.strip()).casefold()
                for term in raw_terms
            ))
            if len(set(required_terms)) != len(required_terms):
                raise ContractValidationError("source-start required terms are invalid")
        # The runtime may use one identifier as the bounded mail anchor when
        # an occurrence is split across body segments.  Native table rows are
        # a separate, row-level surface: retain every protected identifier
        # from the original query there so an item row cannot be admitted from
        # an unrelated PO.
        native_required_terms = required_terms
        query_identifiers = tuple(
            span.exact_token for span in tokenizer.analyze(query_text).protected_identifiers
        )
        if len(required_terms) == 1 and len(query_identifiers) > 1:
            native_required_terms = tuple(sorted(set(query_identifiers)))
        from formowl_mail.human_uat_orchestrator import validated_field_query_hints

        field_query_hints = validated_field_query_hints(
            {**arguments, "request_contract": request_contract, "required_terms": required_terms},
            tool_name="query_mail_evidence" if mail_tool else "query_effective_graph_view",
            available_source_families=available_families,
        )
        placement = _request_term_placement(arguments, mail_tool=mail_tool)
        requested_fields = tuple(request_contract["requested_fields"])
        native_locator = request_contract.get("native_locator")
        if native_locator is not None and (
            not required_terms or placement is not None
            or any(arguments.get(key) is not None for key in (
                "table_query", "exact_inventory_kind", "exact_field", "cursor"))
        ):
            raise ContractValidationError("native attachment page requires ordinary child lookup")
        table_query = arguments.get("table_query")
        # Typed predicates are explicit. For identifier-plus-field lookup, only
        # an identifier actually present in the validated query may start exact
        # binding; output labels and unrelated anchors never become predicates.
        identifier_terms = tuple(
            span.exact_token for span in tokenizer.analyze(query_text).protected_identifiers
        ) or tuple(
            term for term in required_terms
            if term in unicodedata.normalize("NFKC", query_text).casefold()
            and (term.isdecimal() or tokenizer.analyze(term).protected_identifiers)
        )
        if query_class == "exact_set_or_inventory" and table_query is None and (
            request_contract["source_family_scope"] != ["mail"]
            or len(set(identifier_terms)) != 1
            or not tokenizer.analyze(identifier_terms[0]).protected_identifiers
            or arguments.get("cursor") is not None
            or arguments.get("exact_inventory_kind") is not None
        ):
            payload = {
                "status": "pending_review",
                "query_hash": sha256_json(query_text),
                "citations": [],
                "evidence": [],
                "warnings": ["retrieval_projection_unavailable", "skipped_exact"],
            }
            if mail_tool:
                payload["mail_import_session_id"] = selector
                payload["evidence_snippets"] = []
            return payload
        source_budget = {
            "deadline": time.monotonic() + SOURCE_START_EVIDENCE_TIME_BUDGET_MS / 1000,
            "reads": 0, "evidence": 0, "context_bytes": 0,
        }
        # Runtime scopes the absolute TURN deadline; the read/recheck phase
        # separately retains its bounded UAT cap. Cached presentation does not read.
        presentation_deadline = _SOURCE_EVIDENCE_DEADLINE.get()
        if presentation_deadline is not None:
            source_budget["deadline"] = min(source_budget["deadline"], presentation_deadline)
        else:
            presentation_deadline = source_budget["deadline"]
        applicable_fields = {
            normalize_source_occurrence_structured_surface(item["field"])
            for item in (exact_lookup._columns if exact_lookup is not None else ())
            if _exact_column_applicable(revision, item)
            and ("mail" if item["inline_table"] else "attachment_table") in request_contract["source_family_scope"]
        }
        auto_exact = (
            native_locator is None and placement is None and query_class == "evidence_lookup" and bool(requested_fields) and len(identifier_terms) == 1
            and any(normalize_source_occurrence_structured_surface(field) in applicable_fields for field in requested_fields)
        )
        cell = _trace(trace, "phase", "applicability", auto_exact=auto_exact,
                      explicit_exact=table_query is not None, requested_fields=len(requested_fields),
                      hints=len(field_query_hints), query_class=query_class)
        _trace(cell, "finish")
        if table_query is not None:
            with _source_trace_phase(trace, "exact_engine"):
                return _execute_source_start_table(
                    revision, lookup=exact_lookup, arguments=arguments,
                    request_contract=request_contract, mail_tool=mail_tool,
                    selector=selector, identifier_terms=identifier_terms,
                    required_terms=required_terms,
                )
        if auto_exact:
            with _source_trace_phase(trace, "exact_engine"):
                exact_payload = _execute_source_start_table(
                    revision, lookup=exact_lookup, arguments=arguments, request_contract=request_contract,
                    mail_tool=mail_tool, selector=selector, identifier_terms=identifier_terms,
                    required_terms=required_terms, automatic=True, source_budget=source_budget,
                )
            # Partial field support must be disclosed without an automatic
            # recheck. Only a validated all-fields miss may continue, and only
            # through the existing same-scope reader and its remaining caps.
            if (exact_payload["status"] in {"clarification_required", "permission_denied", "error", "failed"}
                    or exact_payload.get("requested_field_coverage", {}).get("supported_fields")):
                return exact_payload
        query_terms: set[str] = set()
        protected_terms: set[str] = set()
        active_family: str | None = None
        active_selector: str | None = selector
        mail_parents_by_occurrence: dict[tuple[str, str, str, str], Observation] = {}
        unresolved_parent_binding = False
        attachment_parents: dict[tuple[str, str], Observation] = {}
        last_anchor: Observation | None = None
        context_anchor: Observation | None = None
        table_evidence: dict[str, dict[str, Any]] = {}
        admitted_context_bytes = source_budget["context_bytes"]
        context_limit_reached = False
        admitted_hashes: set[str] = set()
        admitted_items: list[dict[str, Any]] = []
        reserved_native_slots = 0
        deferred: list[tuple[Observation, str, dict[str, Any], str | None, str | None]] = []
        presentation_cache: list[dict[str, Any]] = []
        overflow_hashes: set[str] = set()
        selection_hits: dict[str, set[tuple[int, str]]] = {}
        field_terms: list[set[str]] = []
        annotation_ids: tuple[str, ...] = ()
        annotation_hashes: tuple[str, ...] = ()
        annotation_target: str | None = None

        def cache_overflow(item):
            # This seam receives a fully guarded/projected unit, never a source ref.
            if (auto_exact or deferred or not field_terms or not _ordinary_presentation_unit(item)
                    or time.monotonic() >= source_budget["deadline"]):
                return
            units = {entry["citation_hash"]: entry for entry in (*admitted_items, *presentation_cache)}
            if item["citation_hash"] not in units and len(units) >= 128:
                return
            standalone, truncated = _bounded_mail_header_groups([item], limit=limit)
            if truncated or len(json.dumps(standalone, ensure_ascii=False).encode("utf-8")) > 16 * 1024:
                return
            for entry in (*admitted_items, *presentation_cache, item):
                key = entry["citation_hash"]
                if key not in selection_hits:
                    if time.monotonic() >= source_budget["deadline"]:
                        return
                    words = set(tokenizer.analyze(entry.get("snippet", "")).tokens)
                    selection_hits[key] = {(i, word) for i, terms in enumerate(field_terms)
                                           for word in terms.intersection(words)}
            pool = list(presentation_cache)
            if item["citation_hash"] not in {entry["citation_hash"] for entry in pool}:
                pool.append(item)
            kept = []
            covered = set().union(*(selection_hits.get(entry["citation_hash"], set()) for entry in admitted_items))
            while pool and time.monotonic() < source_budget["deadline"]:
                best = max(range(len(pool)), key=lambda i: _soft_unit_utility(
                    selection_hits[pool[i]["citation_hash"]] - covered,
                ))
                entry = pool.pop(best)
                records, truncated = _bounded_mail_header_groups([*kept, entry], limit=limit)
                if (not truncated and len(records) <= limit
                        and len(json.dumps(records, ensure_ascii=False).encode("utf-8")) <= 16 * 1024):
                    kept.append(entry)
                    covered.update(selection_hits[entry["citation_hash"]])
            if time.monotonic() < source_budget["deadline"]:
                presentation_cache[:] = kept
                overflow_hashes.add(item["citation_hash"])
            retained = {entry["citation_hash"] for entry in (*admitted_items, *presentation_cache)}
            overflow_hashes.intersection_update(retained)
            for key in tuple(selection_hits):
                if key not in retained:
                    del selection_hits[key]
        deferred_hashes: set[str] = set()
        deferred_families: set[str] = set()
        deferred_replay: tuple[Observation, str, dict[str, Any]] | None = None

        def admit(observation: Observation, item: dict[str, Any], scope_id: str):
            nonlocal admitted_context_bytes, context_limit_reached
            observation_hash = sha256_json(observation.to_dict())
            if observation_hash in annotation_hashes:
                item["source_context"] = {
                    **item.get("source_context", {}),
                    "annotation_pin": revision.reviewed_annotation_pin,
                    "candidate_ids": [entry["candidate_atom_id"] for entry in revision.reviewed_source_annotations
                                      if entry["candidate_atom_id"] in annotation_ids
                                      and observation_hash in entry["source_hashes"]],
                    "exact_field_proof": False,
                }
            if query_class == "evidence_lookup" and observation_hash not in admitted_hashes:
                if observation_hash in deferred_hashes and deferred_replay is None:
                    _trace(trace, "decision", "duplicate_deferred", observation_hash)
                    return None
                # Reuse final presentation's atomic body/header grouping. Charge
                # the actual wire array, including deduplication and separators,
                # before publishing an anchor or any of its dependent headers.
                candidate, truncated = _bounded_mail_header_groups(
                    [*admitted_items, item], limit=max(0, limit - source_budget["evidence"]),
                    byte_limit=16 * 1024 - source_budget["context_bytes"],
                )
                size = len(json.dumps(candidate, ensure_ascii=False).encode("utf-8"))
                if (truncated or len(candidate) > max(0, limit - source_budget["evidence"])
                        or source_budget["context_bytes"] + size > 16 * 1024):
                    context_limit_reached = True
                    cache_overflow(item)
                    _trace(trace, "decision", "context_limit", observation_hash)
                    return None
                if deferred_replay is None and (
                    active_family in deferred_families
                    or len(candidate) > max(0, limit - source_budget["evidence"] - reserved_native_slots)
                ):
                    # Reserve items, not a byte fraction: a large intact paragraph
                    # may still fit when later native phases have no matches.
                    # Keep bounded, already-validated groups, never source refs
                    # that would require another hydration or permission lookup.
                    buffered, buffer_truncated = _bounded_mail_header_groups(
                        [*(entry[2] for entry in deferred), item],
                        limit=max(0, limit - source_budget["evidence"]),
                        byte_limit=16 * 1024 - source_budget["context_bytes"],
                    )
                    if (buffer_truncated or len(buffered) > max(0, limit - source_budget["evidence"])
                            or len(json.dumps(buffered, ensure_ascii=False).encode("utf-8"))
                            > 16 * 1024 - source_budget["context_bytes"]):
                        context_limit_reached = True
                        _trace(trace, "decision", "context_limit", observation_hash)
                    else:
                        deferred_selector = (item.get("mail_import_session_id")
                                             if active_family in {"attachment_table", "mail_inline_table"}
                                             else active_selector)
                        deferred.append((observation, scope_id, item, active_family, deferred_selector))
                        if (not auto_exact and active_family in {"mail", "document_text"}
                                and time.monotonic() < source_budget["deadline"]):
                            # Original reservation cache wins; never evict it for new overflow.
                            if overflow_hashes:
                                presentation_cache.clear()
                                overflow_hashes.clear()
                                selection_hits.clear()
                            presentation_cache.append(item)
                        deferred_hashes.add(observation_hash)
                        _trace(trace, "decision", "deferred", observation_hash)
                    # Later selectors/candidates in this family cannot overtake
                    # the deferred prefix when the unused slots are returned.
                    deferred_families.add(active_family)
                    return None
                admitted_items.append(item)
                # Reserve the combined candidate bound even if later units fit normally.
                while overflow_hashes and len(admitted_items) + len(presentation_cache) > 128:
                    dropped = presentation_cache.pop()
                    overflow_hashes.discard(dropped["citation_hash"])
                    selection_hits.pop(dropped["citation_hash"], None)
                admitted_hashes.add(observation_hash)
                admitted_context_bytes = source_budget["context_bytes"] + size
                _trace(trace, "decision", "admitted", observation_hash)
                return observation_hash, item
            size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
            if observation_hash not in admitted_hashes:
                if admitted_context_bytes + size > 16 * 1024:
                    context_limit_reached = True
                    _trace(trace, "decision", "context_limit", observation_hash)
                    return None
                admitted_hashes.add(observation_hash)
                admitted_context_bytes += size
            _trace(trace, "decision", "admitted", observation_hash)
            return observation_hash, item

        def begin(deadline: float) -> None:
            nonlocal query_terms, protected_terms, annotation_ids, annotation_hashes, annotation_target
            check_source_evidence_deadline(deadline)

            analysis = tokenizer.analyze(query_text)
            query_terms = set(analysis.tokens)
            protected_terms = {item.exact_token for item in analysis.protected_identifiers}
            # The UAT agent may enter a multi-identifier mail occurrence with
            # one validated PO anchor so that the source reader can expand its
            # same-occurrence siblings.  Keep the anchor's protected-token
            # guard aligned with that bounded entry condition; otherwise the
            # later all-identifiers veto rejects the very anchor selected for
            # the governed context walk.
            if required_terms and len(required_terms) == 1 and len(protected_terms) > 1:
                protected_terms = set(required_terms)
            if arguments.get("reviewed_annotation_ids") or arguments.get("reviewed_annotation_pin") is not None:
                if query_class != "evidence_lookup" or auto_exact or placement is not None or native_locator is not None:
                    raise ContractValidationError("UAT reviewed annotation route is unsupported")
                annotation_ids, annotation_hashes, annotation_target = _select_reviewed_annotation_sources(
                    revision, arguments={**arguments, "request_contract": request_contract,
                                         "required_terms": required_terms},
                    catalog=annotation_catalog, deadline=deadline)
                cell = _trace(trace, "phase", "project", reviewed_annotation_selection=True,
                              selected_count=len(annotation_ids), source_count=len(annotation_hashes),
                              annotation_pin=revision.reviewed_annotation_pin)
                _trace(cell, "finish")
            # A Query Agent may add presentation instructions to query_text.
            # Rank source candidates by the validated evidence constraints, not
            # those instruction words. Multiword constraints use the same frozen
            # profile as the source postings; the full matcher remains unchanged.
            lookup_terms = set()
            for term in (placement.child_terms if placement is not None else required_terms):
                check_source_evidence_deadline(deadline)
                lookup_terms.update(tokenizer.analyze(term).tokens)
            project.source_lookup_terms = tuple(sorted(
                lookup_terms if required_terms else query_terms
            ))
            if query_class == "evidence_lookup" and not auto_exact:
                for field in requested_fields:
                    check_source_evidence_deadline(deadline)
                    field_terms.append(set(tokenizer.analyze(field).tokens))
            preferred_terms: set[str] = set()
            for field in (*requested_fields, *(hint["text"] for hint in field_query_hints)) if required_terms else ():
                check_source_evidence_deadline(deadline)
                preferred_terms.update(tokenizer.analyze(field).tokens)
            project.source_lookup_preferred_terms = tuple(sorted(preferred_terms))
            cell = _trace(trace, "phase", "lookup_terms", required_term_count=len(project.source_lookup_terms),
                          preferred_term_count=len(project.source_lookup_preferred_terms))
            _trace(cell, "finish")
            check_source_evidence_deadline(deadline)

        def project(observation: Observation, scope_id: str, deadline: float):
            nonlocal unresolved_parent_binding, last_anchor
            check_source_evidence_deadline(deadline)
            last_anchor = None
            semantic_hash = sha256_json(observation.to_dict()) if annotation_hashes else None
            semantic_match = semantic_hash in annotation_hashes
            if semantic_match:
                # Only the reviewed identity anchor may be source-linked rather
                # than repeated in a child paragraph. ALL other literals survive.
                if not _reviewed_annotation_literals_match(
                    observation, required_terms=required_terms, target=annotation_target,
                    protected_terms=protected_terms, tokenizer=tokenizer, deadline=deadline,
                ):
                    return None
            if deferred_replay is not None:
                cached_observation, cached_scope, item = deferred_replay
                if observation is not cached_observation or scope_id != cached_scope:
                    raise ContractValidationError("source-start deferred binding is invalid")
                return admit(observation, item, scope_id)
            if placement is not None and (active_family != "mail" or observation.observation_type != "email_body_segment"):
                return None
            if observation.observation_id in table_evidence:
                return admit(observation, table_evidence[observation.observation_id], scope_id)

            def public_text(value: str) -> str:
                # A native PDF page can be one paragraph. Literal field/anchor
                # windows may detach its value from the identifier. Retain the
                # whole redacted text; admit() charges the serialized item to
                # the shared UTF-8 budget and stops with context_limit if it
                # cannot fit, without silently presenting a clipped paragraph.
                return redact_public_raw_references(value)[0]

            if active_family == "mail":
                payload = to_plain(observation.payload or {})
                location = to_plain(observation.location)
                if observation.observation_type == "email_attachment_occurrence" or _is_attachment_text_observation(observation):
                    if (
                        (active_selector is not None and scope_id != active_selector)
                        or (active_selector is None and scope_id not in source.source_scope_ids)
                        or not authorized_permission_scope_matches(
                            observation.permission_scope, authorized_source=source,
                            source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                        )
                    ):
                        return None
                    if observation.observation_type == "email_attachment_occurrence":
                        child_id = payload.get("child_asset_id")
                        if isinstance(child_id, str) and child_id:
                            attachment_parents[(scope_id, child_id)] = observation
                        _trace(trace, "count", "parent_context")
                        return None  # Parent binding is not a child text match.
                    # The reader emits the hash-checked parent first, counting
                    # hydration against this same scan's read/time limits.
                    parent = attachment_parents.get((scope_id, observation.asset_id))
                    if parent is None:
                        unresolved_parent_binding = True
                        _trace(trace, "count", "parent_unresolved")
                        return None
                    lineage = _attachment_child_lineages({
                        parent.observation_id: parent, observation.observation_id: observation,
                    })[observation.observation_id]
                    if native_locator is not None and (
                        type(location.get("page")) is not int or location["page"] != native_locator["page"]
                    ):
                        return None
                    text = observation.text or observation.caption or ""
                    normalized = unicodedata.normalize("NFKC", text).casefold()
                    if semantic_match:
                        pass  # Reviewed identity/field binding; source guards above still apply.
                    elif required_terms:
                        if not all(term in normalized for term in required_terms):
                            return None
                    elif not query_terms.issubset(set(tokenizer.analyze(text).tokens)):
                        return None
                    if not semantic_match and protected_terms and not protected_terms.issubset(set(tokenizer.analyze(text).tokens)):
                        return None
                    parent_payload = parent.payload or {}
                    message_fingerprint = parent_payload.get("message_fingerprint")
                    if not isinstance(message_fingerprint, str) or not message_fingerprint:
                        unresolved_parent_binding = True
                        _trace(trace, "count", "parent_unresolved")
                        return None
                    snippet_payload = {
                        "source_type": "mail_attachment_text",
                        "source_observation_id": observation.observation_id,
                        "email_message_id": stable_resource_contract_id(
                            "emailmsg", "EmailMessage", {"message_fingerprint": message_fingerprint},
                        ),
                        "message_occurrence_id": lineage.message_occurrence_id,
                        "snippet": public_text(text),
                        "source_observation_hash": sha256_json(observation.to_dict()),
                        "citation_hash": sha256_json(observation.to_dict()),
                        "occurrence_lineage_fingerprint": lineage.lineage_fingerprint,
                        "source_scope_fingerprint": sha256_json(scope_id),
                        "attachment_locator": {
                            "block_type": observation.observation_type,
                            "child_asset_id": lineage.child_asset_id,
                            "parent_attachment_observation_id": lineage.parent_attachment_observation_id,
                            **{
                                key: value for key, value in location.items()
                                if key in {"page", "paragraph_index", "block_index", "slide", "shape_index", "list_item_index"}
                                and type(value) is int and value >= 1
                            },
                        },
                        "revision_binding": {
                            "source_authority_fingerprint": revision.safe_binding["source_authority_fingerprint"],
                            "source_session_binding_fingerprint": revision.safe_binding["source_session_binding_fingerprint"],
                        },
                    }
                    if active_selector is not None:
                        snippet_payload["mail_import_session_id"] = active_selector
                    check_source_evidence_deadline(deadline)
                    snippet = _mail_header_context(
                        observation, _safe_snippet(snippet_payload),
                        mail_parents_by_occurrence.get((
                            scope_id, parent.asset_id,
                            (_attachment_mail_parent_link(parent) or {}).get("parent_extractor_run_id", parent.extractor_run_id),
                            lineage.message_occurrence_id,
                        )), source=source, scope_id=scope_id, attachment_parent=parent,
                    )
                    return admit(observation, snippet, scope_id)
                occurrence_id = location.get("message_occurrence_id")
                message_fingerprint = payload.get("message_fingerprint")
                if (
                    (active_selector is not None and scope_id != active_selector)
                    or (active_selector is None and scope_id not in source.source_scope_ids)
                    or observation.modality != "mail"
                    or observation.observation_type not in REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES
                    or not authorized_permission_scope_matches(
                        observation.permission_scope,
                        authorized_source=source,
                        source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                    )
                ):
                    _trace(trace, "count", "scope_rejected")
                    return None
                lineage = source_occurrence_lineage_from_observation(
                    observation, authorized_source=source,
                )
                if (
                    observation.observation_type == "email_message"
                    and isinstance(message_fingerprint, str)
                    and isinstance(occurrence_id, str)
                ):
                    mail_parents_by_occurrence[(
                        scope_id, observation.asset_id, observation.extractor_run_id, occurrence_id,
                    )] = (
                        observation
                    )
                if native_locator is not None:
                    return None  # Outer headers are dependent metadata, never a page hit.
                if not semantic_match and placement is None and context_anchor is None and (
                    _source_mail_observation_match(
                        observation,
                        query_terms=query_terms,
                        required_terms=required_terms or None,
                        protected_query_tokens=protected_terms,
                        tokenizer_profile=tokenizer,
                        deadline_monotonic=deadline,
                    ) is None
                ):
                    _trace(trace, "count", "matcher_rejected")
                    return None
                if message_fingerprint is None and isinstance(occurrence_id, str):
                    parent = mail_parents_by_occurrence.get(
                        (scope_id, observation.asset_id, observation.extractor_run_id, occurrence_id)
                    )
                    if placement is not None:
                        pair = _SOURCE_OCCURRENCE_PAIR.get()
                        parent = pair[1] if pair is not None and pair[0] is observation else None
                    message_fingerprint = (parent.payload or {}).get("message_fingerprint") if parent else None
                if not isinstance(message_fingerprint, str) or not isinstance(occurrence_id, str):
                    unresolved_parent_binding = True
                    _trace(trace, "count", "parent_unresolved")
                    return None
                snippet_payload = {
                    "source_type": {
                        "email_body_segment": "mail_body_segment",
                        "email_message": "mail_message",
                        "email_header": "mail_header",
                    }[observation.observation_type],
                    "source_observation_id": observation.observation_id,
                    "email_message_id": stable_resource_contract_id(
                        "emailmsg", "EmailMessage",
                        {"message_fingerprint": message_fingerprint},
                    ),
                    "message_occurrence_id": occurrence_id,
                    "subject": payload.get("subject"),
                    "snippet": public_text(observation.text or ""),
                    "source_observation_hash": sha256_json(observation.to_dict()),
                    "citation_hash": sha256_json(observation.to_dict()),
                    "occurrence_lineage_fingerprint": lineage.lineage_fingerprint,
                    "source_scope_fingerprint": sha256_json(scope_id),
                    "revision_binding": {
                        "source_authority_fingerprint": revision.safe_binding[
                            "source_authority_fingerprint"
                        ],
                        "source_session_binding_fingerprint": revision.safe_binding[
                            "source_session_binding_fingerprint"
                        ],
                    },
                }
                if active_selector is not None:
                    snippet_payload["mail_import_session_id"] = active_selector
                if placement is not None:
                    snippet = _placement_mail_group(
                        placement, observation, scope_id, _safe_snippet(snippet_payload), source=source,
                        protected_terms=protected_terms, tokenizer=tokenizer,
                    )
                    if snippet is None:
                        return None
                else:
                    snippet = _mail_header_context(
                        observation, _safe_snippet(snippet_payload),
                        mail_parents_by_occurrence.get((
                            scope_id, observation.asset_id, observation.extractor_run_id, occurrence_id,
                        )), source=source, scope_id=scope_id,
                    )
            elif active_family == "document_text":
                if (
                    observation.modality != "text"
                    or observation.observation_type not in {"heading", "paragraph"}
                    or scope_id not in source.source_scope_ids
                    or not authorized_permission_scope_matches(
                        observation.permission_scope,
                        authorized_source=source,
                        source_kind=AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
                    )
                ):
                    return None
                text = observation.text or observation.caption or ""
                if not text:
                    return None
                normalized = unicodedata.normalize("NFKC", text).casefold()
                if semantic_match or context_anchor is not None:
                    pass  # Reader already revalidated this neighbor against the matched anchor.
                elif required_terms:
                    if not all(term in normalized for term in required_terms):
                        return None
                else:
                    source_tokens = set(tokenizer.analyze(text).tokens)
                    if not query_terms.intersection(source_tokens):
                        return None
                source_tokens = set() if context_anchor is not None else set(tokenizer.analyze(text).tokens)
                if not semantic_match and context_anchor is None and protected_terms and not protected_terms.issubset(source_tokens):
                    return None
                lineage = source_occurrence_lineage_from_observation(
                    observation, authorized_source=source,
                )
                snippet = {
                    "snippet": public_text(text),
                    "citation_hash": sha256_json(observation.to_dict()),
                    "occurrence_lineage_fingerprint": lineage.lineage_fingerprint,
                    "source_scope_fingerprint": sha256_json(scope_id),
                    "document_locator": {
                        "block_type": observation.observation_type,
                        "asset_id": lineage.asset_id,
                        "extractor_run_id": lineage.extractor_run_id,
                        "line_start": lineage.line_start,
                        "line_end": lineage.line_end,
                    },
                    "revision_binding": {
                        "source_authority_fingerprint": revision.safe_binding[
                            "source_authority_fingerprint"
                        ],
                        "source_session_binding_fingerprint": revision.safe_binding[
                            "source_session_binding_fingerprint"
                        ],
                    },
                }
            else:
                raise ContractValidationError("source-start family is invalid")
            if context_anchor is not None:
                anchor_hash = sha256_json(context_anchor.to_dict())
                snippet["source_context"] = {
                    "relationship": "same_source_neighbor",
                    "anchor_citation_hash": anchor_hash,
                    "anchor_source_observation_id": context_anchor.observation_id,
                    "identifier_hit": False,
                    "exact_field_proof": False,
                }
                # Existing compact evidence paths retain snippet text. Keep the
                # relationship visible there too, without attributing a field
                # value to the identifier's own source occurrence.
                snippet["snippet"] = (
                    f"[same-source context; anchor observation {context_anchor.observation_id}; "
                    f"anchor citation {anchor_hash}; "
                    "not an identifier hit or exact field proof] " + snippet["snippet"]
                )
            if query_class == "exact_set_or_inventory":
                # Exact membership proves native textual occurrence, not that
                # the current author made a new assertion at the outer date.
                # Quoted history remains evidence, never an authored event.
                snippet["source_context"] = {
                    "relationship": "native_identifier_occurrence",
                    "authored_assertion_verified": False, "event_date_verified": False,
                }
                snippet["snippet"] = (
                    "[native identifier occurrence; not proof of an authored update or event date] "
                    + snippet["snippet"]
                )
            projected = admit(observation, snippet, scope_id)
            if projected is not None and context_anchor is None:
                last_anchor = observation
            return projected

        def read_source(**kwargs: Any) -> RevisionOwnedMailSourceScan:
            nonlocal active_family, active_selector, context_anchor
            nonlocal reserved_native_slots, deferred_replay, context_limit_reached
            def consume(observation: Observation, scope: str) -> bool:
                return kwargs["observation_callback"](observation, scope) and (
                    query_class == "evidence_lookup" or not context_limit_reached
                )

            def consume_context(anchor: Observation, neighbor: Observation, scope: str) -> bool:
                nonlocal context_anchor
                if sha256_json(anchor.to_dict()) not in admitted_hashes:
                    return True
                context_anchor = anchor
                try:
                    return consume(neighbor, scope)
                finally:
                    context_anchor = None

            remaining = max(0, kwargs["max_observations"] - source_budget["reads"])
            scanned = 0
            families = [
                family for family in request_contract["source_family_scope"]
                if family in available_families
            ]
            if native_locator is None and query_class != "exact_set_or_inventory" and "mail" in families and exact_lookup is not None and revision.exact_lookup_manifest.get(
                "counts", {}
            ).get("inline_authorized_row", 0):
                families.append("mail_inline_table")
            # Reviewed hashes are already pinned to the source revision. Use
            # only their sealed helper metadata to prioritize the corresponding
            # family; the normal authority/hash/permission reader remains the
            # sole hydration path. This avoids spending an ordinary family's
            # fractional slice on a preferred mail parent before its child can
            # be emitted, without changing the shared deadline or read cap.
            preferred_families: set[str] = set()
            helper_for_hash = getattr(records.runtime_store, "helper_for_hash", None)
            if annotation_hashes and callable(helper_for_hash):
                for observation_hash in annotation_hashes:
                    helper = helper_for_hash(observation_hash)
                    if isinstance(helper, Mapping):
                        family = helper.get("retrieval_source_family")
                        if family == "mail" and "mail" in families:
                            preferred_families.add("mail")
                        elif family == "document_text" and "document_text" in families:
                            preferred_families.add("document_text")
            native_counts = revision.exact_lookup_manifest.get("counts", {})
            pending_native = {
                family for family in families
                if native_locator is None and query_class == "evidence_lookup" and exact_lookup is not None
                and native_counts.get({
                    "attachment_table": "attachment_authorized_row",
                    "mail_inline_table": "inline_authorized_row",
                }.get(family), 0) > 0
            }
            # Do not invert starvation at tiny limits: leave the first ordinary
            # representation room for its atomic mail pair (or nonmail item).
            reservation_limit = max(0, limit - source_budget["evidence"] - (2 if "mail" in families else 1))
            # Combine adjacent native engines, never authorization families or
            # their admission slots. Interleaved scopes retain the legacy path.
            engines = [(family,) for family in families]
            for index in range(len(families) - 1):
                pair = tuple(families[index:index + 2])
                if (len(pending_native) == 2 and set(pair) == pending_native
                        and set(pair) != {"attachment_table", "mail_inline_table"}):
                    engines[index:index + 2] = [pair]
                    break
            def preferred_engine(engine: tuple[str, ...]) -> bool:
                return any(item in preferred_families or item == "attachment_table"
                           for item in engine)
            # When mail and attachment tables share a turn, the mail reader
            # can consume the bounded source budget before the native table
            # engine starts. Give the attachment table its first bounded
            # slice so a native PO/item row is not starved by body context.
            engines.sort(key=lambda engine: (
                not preferred_engine(engine),
                not any(item == "attachment_table" for item in engine),
            ))

            def begin_native_family(family: str) -> None:
                nonlocal active_family, reserved_native_slots
                active_family = "mail_inline_table" if family == "mail" else family
                pending_native.discard(active_family)
                reserved_native_slots = min(len(pending_native), reservation_limit)

            incomplete_reason: str | None = None
            for family_index, engine in enumerate(engines):
                family = engine[0]
                if native_locator is not None and family != "mail":
                    incomplete_reason = "unsupported_native_locator"
                    continue
                active_family = family
                pending_native.discard(family)
                reserved_native_slots = min(len(pending_native), reservation_limit)
                selectors = (
                    (selector,) if family == "mail" and mail_tool
                    else (selector_ids or (None,)) if family == "mail"
                    else (None,)
                )
                family_remaining = remaining - scanned
                preferred = preferred_engine(engine)
                ordinary_engines_left = sum(
                    not preferred_engine(candidate) for candidate in engines[family_index:]
                )
                family_left = ordinary_engines_left if not preferred else 1
                family_limit = family_remaining if preferred else (
                    family_remaining // max(1, ordinary_engines_left)
                )
                if family_limit <= 0:
                    incomplete_reason = "observation_limit"
                    break
                now = time.monotonic()
                # Every authorized family gets a share of the same absolute
                # deadline, including mail/document-only requests. An earlier
                # slow family must not spend a later family's allocation.
                family_deadline = (
                    kwargs["deadline_monotonic"] if preferred else
                    now + max(0, kwargs["deadline_monotonic"] - now) / max(1, family_left)
                )
                engine_cell = _trace(trace, "phase", "engine", families=engine,
                                     max_reads=family_limit, deadline=family_deadline,
                                     reserved_slots=reserved_native_slots)
                if family in {"attachment_table", "mail_inline_table"}:
                    native_metrics = ({f"native_{stage}_{measure}": 0
                                       for stage in ("terms", "values", "rows")
                                       for measure in ("attempted", "completed", "wall_ms", "cpu_ms")}
                                      if engine_cell is not None else None)
                    scan = exact_lookup.scan_source_rows(
                        required_terms=native_required_terms,
                        query_text=query_text,
                        source_families=tuple("mail" if item == "mail_inline_table" else item for item in engine),
                        mail_import_session_id=selector if mail_tool else None,
                        max_observations=family_limit,
                        deadline_monotonic=family_deadline,
                        observation_callback=consume,
                        evidence_by_id=table_evidence,
                        _phase_metrics=native_metrics,
                        **({"begin_family": begin_native_family} if len(engine) == 2 else {}),
                    )
                    _trace(engine_cell, "finish", scanned=scan.scanned_observation_count,
                           complete=scan.complete, stop=scan.stop_reason, **(native_metrics or {}))
                    scanned += scan.scanned_observation_count
                    if not scan.complete:
                        incomplete_reason = (
                            "context_limit" if context_limit_reached and query_class != "evidence_lookup"
                            else scan.stop_reason
                        )
                        if incomplete_reason == "callback" or time.monotonic() >= kwargs["deadline_monotonic"]:
                            return RevisionOwnedMailSourceScan((), scanned, False, incomplete_reason)
                        if incomplete_reason == "context_limit":
                            # A native row exhausted its reader-local context,
                            # not the shared ordinary-item capacity. Stop all
                            # further reads, retaining incomplete, and let the
                            # original callback govern cached-only backfill.
                            break
                    continue
                family_start_scanned = scanned
                for selector_index, family_selector in enumerate(selectors):
                    active_selector = family_selector
                    selectors_left = len(selectors) - selector_index
                    left = (family_limit - (scanned - family_start_scanned)) // selectors_left
                    if left <= 0:
                        incomplete_reason = "observation_limit"
                        break
                    now = time.monotonic()
                    selector_deadline = now + max(0, family_deadline - now) / selectors_left
                    selector_cell = _trace(trace, "phase", "selector", selector_index=selector_index,
                                           _binding=(family_selector,), max_reads=left, deadline=selector_deadline)
                    scan = records.scan_authorized_observations(
                        source_family=family, source_scope_ids=(
                            source.source_scope_ids if family == "document_text" else ()
                        ),
                        mail_import_session_id=family_selector,
                        max_observations=left,
                        deadline_monotonic=selector_deadline,
                        observation_callback=consume,
                        context_anchor_callback=lambda item, scope: query_class != "exact_set_or_inventory" and item is last_anchor,
                        context_callback=consume_context,
                        _allow_parallel_hydration=query_class == "evidence_lookup",
                        **({"preferred_observation_hashes": annotation_hashes} if annotation_hashes else {}),
                    )
                    if not isinstance(scan, RevisionOwnedMailSourceScan):
                        raise ContractValidationError("source-start scan result is invalid")
                    _trace(selector_cell, "finish", scanned=scan.scanned_observation_count,
                           complete=scan.complete, stop=scan.stop_reason)
                    scanned += scan.scanned_observation_count
                    if not scan.complete:
                        incomplete_reason = (
                            "context_limit" if context_limit_reached and query_class != "evidence_lookup"
                            else scan.stop_reason or "deadline"
                        )
                        if incomplete_reason in {"callback", "context_limit"} or time.monotonic() >= kwargs["deadline_monotonic"]:
                            _trace(engine_cell, "finish", scanned=scanned - family_start_scanned,
                                   complete=False, stop=incomplete_reason)
                            return RevisionOwnedMailSourceScan(
                                (), scanned, False, incomplete_reason,
                            )
                _trace(engine_cell, "finish", scanned=scanned - family_start_scanned,
                       complete=incomplete_reason is None, stop=incomplete_reason)
            reserved_native_slots = 0
            for entry in deferred:
                if time.monotonic() >= kwargs["deadline_monotonic"]:
                    incomplete_reason = "deadline"
                    break
                # Re-enter the original publisher, not a reader. Its callback
                # count and absolute deadline still govern cached backfill, even
                # though the candidate was already charged/validated on arrival.
                active_family, active_selector = entry[3:]
                deferred_replay = entry[:3]
                try:
                    _trace(trace, "count", "replayed")
                    keep_scanning = kwargs["observation_callback"](entry[0], entry[1])
                finally:
                    deferred_replay = None
                if not keep_scanning:
                    incomplete_reason = "callback"
                    break
            if deferred_hashes - admitted_hashes:
                context_limit_reached = True
            active_family = None
            active_selector = selector
            if context_limit_reached and incomplete_reason not in {"deadline", "observation_limit", "callback"}:
                incomplete_reason = "context_limit"
            if incomplete_reason is None and unresolved_parent_binding:
                incomplete_reason = "source_parent_binding_unresolved"
            return RevisionOwnedMailSourceScan(
                (), scanned, incomplete_reason is None, incomplete_reason,
            )

        limit = arguments.get("limit" if mail_tool else "page_size", 5 if mail_tool else 10)
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ContractValidationError("source-start evidence limit is invalid")
        if query_class == "exact_set_or_inventory":
            # Primary native execution, not the evidence-lookup automatic
            # recheck. Keep the original exact request and all its constraints.
            native: dict[str, Observation] = {}
            matches: dict[str, dict[str, Any]] = {}
            deadline = source_budget["deadline"]
            scan = RevisionOwnedMailSourceScan((), 0, False, "deadline")
            callbacks = 0

            def collect_exact(observation: Observation, scope: str) -> bool:
                nonlocal callbacks
                check_source_evidence_deadline(deadline)
                if callbacks >= SOURCE_EVIDENCE_OBSERVATION_LIMIT:
                    return False
                callbacks += 1
                # This existing provider supports native mail occurrences only;
                # attachments/documents must never masquerade as mail members.
                if (observation.modality != "mail"
                        or observation.observation_type not in REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES):
                    return True
                projected = project(observation, scope, deadline)
                if projected is not None and identifier_terms[0] in {
                    span.exact_token for span in tokenizer.analyze(observation.text or "").protected_identifiers
                }:
                    citation, item = projected
                    native[citation] = observation
                    matches[citation] = item
                check_source_evidence_deadline(deadline)
                return len(matches) < min(limit, 100)

            exact_result = None
            evidence: list[dict[str, Any]] = []
            header_groups_truncated = False
            try:
                begin(deadline)
                with source_evidence_query_terms_scope(
                    project.source_lookup_terms,
                    preferred_terms=project.source_lookup_preferred_terms,
                ):
                    scan = read_source(
                        max_observations=SOURCE_EVIDENCE_OBSERVATION_LIMIT,
                        deadline_monotonic=deadline, observation_callback=collect_exact,
                    )
                check_source_evidence_deadline(deadline)
                evidence, header_groups_truncated = _bounded_mail_header_groups(
                    tuple(matches.values()), limit=min(limit, 100),
                )
                visible = {item["citation_hash"] for item in evidence}
                observations = tuple(item for key, item in native.items() if key in visible)
                if observations:
                    hashes = tuple(sorted((item.observation_id, sha256_json(item.to_dict())) for item in observations))
                    lineages = normalized_authorized_observation_lineages(
                        observations, authorized_source=source,
                        occurrence_lineages=tuple(source_occurrence_lineage_from_observation(item, authorized_source=source)
                                                  for item in observations),
                    )
                    provider_input = SimpleNamespace(
                        authorized_observations=observations, authorized_observation_hashes=hashes,
                        occurrence_lineages=lineages, requester_user_id=arguments["requester_user_id"],
                        workspace_id=arguments["workspace_id"], authorized_source_scope_ids=source.source_scope_ids,
                        source_session_binding_fingerprint=revision.safe_binding["source_session_binding_fingerprint"],
                        index=SimpleNamespace(_runtime_components=SimpleNamespace(tokenizer_profile=tokenizer)),
                    )
                    providers = _build_ingestion_source_occurrence_providers(provider_input, include_table_providers=False)
                    provider = next(item for item in providers
                                    if item.normalized_field == "message_occurrence.direct_source_identifier_v1")
                    # A query-keyed bounded sample cannot prove a complete set,
                    # total, latest state or absence, even if its reader finished.
                    provider = replace(provider, source_asset_reason_counts=(("unresolved", 1),))
                    plan = SemanticQueryPlan(
                        query_hash=sha256_json(query_text), query_class="exact_set_or_inventory",
                        source_kind=source.source_kind, source_scope_ids=source.source_scope_ids,
                        workspace_id=arguments["workspace_id"], requester_user_id=arguments["requester_user_id"],
                        required_permissions=("read",), user_graph_revision_id="unavailable",
                        canonical_graph_revision_id="unavailable", ontology_revision_id="unavailable",
                        assembly_policy_id="source_start", allowed_paths=(), seed_node_ids=(), max_hops=0,
                        max_fanout=0, candidate_limit=0, result_limit=min(limit, 100), evidence_budget=128,
                        time_budget_ms=SOURCE_EVIDENCE_TIME_BUDGET_MS, repair_budget=0, repair_attempt_count=0,
                        claim_strength="cited_evidence", exact_operation="inventory_with_count",
                        exact_inventory_kind=provider.resource_kind, exact_normalized_field=provider.normalized_field,
                        exact_predicate=provider.predicate, exact_operator=provider.operator,
                        exact_source_occurrence_provider_fingerprint=provider.provider_fingerprint,
                        exact_identifier_term_hashes=(sha256_json(identifier_terms[0]),),
                    )
                    check_source_evidence_deadline(deadline)
                    exact_result = execute_deterministic_source_occurrence_inventory(
                        plan=plan, provider=provider, expected_authorized_scope_fingerprint=provider.authorized_scope_fingerprint,
                        page_size=min(limit, 100), cursor=None,
                    )
                    check_source_evidence_deadline(deadline)
            except _SourceEvidenceDeadlineExceeded:
                scan = replace(scan, complete=False, stop_reason="deadline")
                exact_result = None
            # No exact result means no positive or negative inventory claim.
            if exact_result is None:
                evidence = []
            citations = [item["citation_hash"] for item in evidence]
            supported = source_evidence_supported_requested_fields(
                requested_fields, exact_result=exact_result, answer_citation_hashes=tuple(citations),
                verified_citation_lineages=tuple((item["citation_hash"], item["occurrence_lineage_fingerprint"])
                                                for item in evidence),
            )
            missing = [field for field in requested_fields if field not in supported]
            field_coverage = {
                "request_contract_fingerprint": sha256_json(request_contract),
                "requested_fields": list(requested_fields), "supported_fields": list(supported),
                "missing_fields": missing, "status": "incomplete" if missing else "verified", "absence_claim": False,
                "evidence_citation_hashes": sorted(citations),
            }
            field_coverage["coverage_fingerprint"] = sha256_json(field_coverage)
            status = "partial" if evidence else "pending_review"
            payload = {
                "status": status, "query_hash": sha256_json(query_text), "evidence": evidence, "citations": citations,
                "deterministic_exact": exact_result is not None,
                "exact_result": exact_result.to_safe_dict() if exact_result else None,
                "canonical_kg": False, "graph_hits": {"count": 0},
                "coverage": {"status": "incomplete", "absence_claim": False,
                             "scope": "declared_completed_ingestion_jobs", "reason": scan.stop_reason or "source_occurrence_shortlist"},
                "requested_field_coverage": field_coverage,
                "warnings": ["source_occurrence_shortlist_incomplete"],
                "query_agent": {
                    "status": "pending_review", "stop_reason": scan.stop_reason or "source_occurrence_shortlist",
                    "original_query_hash": request_contract["original_query_hash"], "request_contract": dict(request_contract),
                    "context_bundle": {"citation_hashes": citations, "missing_field_hashes": [sha256_json(field) for field in missing],
                                       "source_execution": {"scanned_observation_count": scan.scanned_observation_count,
                                                            "complete": False, "stop_reason": scan.stop_reason}},
                },
                **({"presentation_truncated": True} if header_groups_truncated else {}),
            }
            if mail_tool:
                payload.update(mail_import_session_id=selector, evidence_snippets=evidence,
                               citations=[_citation_for_snippet(item) for item in evidence])
            else:
                payload["answer"] = {"status": status, "text": "Source-backed occurrences are available; coverage is incomplete." if evidence else "",
                                     "answer_hash": sha256_json(payload), "citation_count": len(evidence)}
            validate_public_gateway_payload(payload)
            return payload

        double_check = source_evidence_double_check(
            initial_status="pending_review",
            query_class=query_class,
            result_query_class=query_class,
            initial_warnings=("retrieval_projection_unavailable",),
            verified_evidence_count=0,
            evidence_limit=max(0, limit - source_budget["evidence"]),
            sealed_coverage_complete=coverage_complete,
            read_source=read_source,
            project_observation=project,
            begin=begin,
            requested_fields=requested_fields,
            supported_requested_fields=(),
            deadline_monotonic=source_budget["deadline"],
            time_budget_ms=SOURCE_START_EVIDENCE_TIME_BUDGET_MS,
        )
        evidence, header_groups_truncated = _bounded_mail_header_groups(
            double_check.evidence, limit=max(0, limit - source_budget["evidence"]),
        )
        if context_limit_reached:
            header_groups_truncated = True
            double_check = replace(double_check, warnings=(*double_check.warnings, "context_limit"))
        supported = source_evidence_supported_requested_fields(
            requested_fields,
            exact_result=None,
            answer_citation_hashes=tuple(item.get("citation_hash") for item in evidence),
            verified_citation_lineages=tuple(
                (item["citation_hash"], item["occurrence_lineage_fingerprint"])
                for item in evidence
            ),
        )
        missing = [field for field in requested_fields if field not in supported]
        recovery = {
            "artifact_id": "formowl_bounded_source_recovery_v1",
            "source_family": (
                request_contract["source_family_scope"][0]
                if len(request_contract["source_family_scope"]) == 1
                else "source_neutral"
            ),
            "source_families": list(request_contract["source_family_scope"]),
            "source_family_scope": list(request_contract["source_family_scope"]),
            "query_hash": sha256_json(query_text),
            "initial_status": "pending_review",
            "status": double_check.status or "pending_review",
            "attempted": double_check.scan is not None,
            "scan": (
                {
                    "scanned_observation_count": double_check.scan.scanned_observation_count,
                    "complete": double_check.scan.complete,
                    "stop_reason": double_check.scan.stop_reason,
                } if double_check.scan is not None else None
            ),
            "source_authority_fingerprint": revision.safe_binding["source_authority_fingerprint"],
            "source_session_binding_fingerprint": revision.safe_binding[
                "source_session_binding_fingerprint"
            ],
            "citation_hashes": sorted(item["citation_hash"] for item in evidence),
            "lineage_fingerprints": sorted(
                item["occurrence_lineage_fingerprint"] for item in evidence
            ),
            "evidence": evidence,
            "warnings": list(double_check.warnings),
        }
        recovery["recovery_fingerprint"] = sha256_json(recovery)
        missing_field_hashes = [sha256_json(field) for field in missing]
        coverage_payload = {
            "request_contract_fingerprint": sha256_json(request_contract),
            "requested_fields": list(requested_fields),
            "supported_fields": list(supported),
            "missing_fields": missing,
            "evidence_citation_hashes": recovery["citation_hashes"],
            "status": "incomplete" if missing else "verified",
            "absence_claim": False,
        }
        coverage_payload["coverage_fingerprint"] = sha256_json(coverage_payload)
        query_agent = {
            "status": "pending_review",
            "stop_reason": "retrieval_projection_unavailable",
            "original_query_hash": request_contract["original_query_hash"],
            "request_contract": request_contract,
            "subqueries": [{
                "status": "pending_review",
                "validation_status": "validated_existing_scope_schema_permission",
                "query_hash": sha256_json(query_text),
                "plan_fingerprint": sha256_json({
                    "source_start": True,
                    "request_contract": request_contract,
                    **({"reviewed_annotation_pin": revision.reviewed_annotation_pin,
                        "annotation_ids": annotation_ids} if annotation_ids else {}),
                }),
                "request_contract_fingerprint": sha256_json(request_contract),
            }],
            "warnings": list(double_check.warnings),
            "context_bundle": {
                "citation_hashes": recovery["citation_hashes"],
                "lineage_fingerprints": recovery["lineage_fingerprints"],
                "missing_field_hashes": missing_field_hashes,
                "source_recovery": recovery,
            },
        }
        if annotation_ids:
            query_agent["reviewed_annotation_selection"] = {
                "candidate_atom_ids": list(annotation_ids),
                "nominated_source_observation_ids": list(dict.fromkeys(key
                    for entry in revision.reviewed_source_annotations
                    if entry["candidate_atom_id"] in annotation_ids
                    for key in entry["source_observation_ids"])),
                "admitted_source_observation_hashes": [key for key in annotation_hashes
                    if key in recovery["citation_hashes"]],
                "catalog_pin": annotation_catalog["catalog_pin"],
                "exact_field_proof": False,
            }
        if auto_exact:
            query_agent["exact_first"] = {
                "status": exact_payload["status"],
                "all_requested_fields_missing": True,
                "scanned_observation_count": source_budget["reads"],
                "source_recovery_attempted": double_check.scan is not None,
            }
        query_agent["context_bundle"]["bundle_fingerprint"] = sha256_json(
            query_agent["context_bundle"]
        )
        status = double_check.status or ("ok" if evidence else "pending_review")
        # Normal return is required: reader/drain errors never reach this path.
        presentation_deferred = (
            tuple(presentation_cache)
            if query_class == "evidence_lookup" and not auto_exact
            and double_check.scan is not None and double_check.scan.stop_reason == "deadline"
            and not double_check.scan.complete and time.monotonic() < presentation_deadline
            else ()
        )
        if overflow_hashes and double_check.scan is not None and time.monotonic() < presentation_deadline:
            presentation_deferred = tuple(presentation_cache)
        if mail_tool:
            mail_evidence = []
            citations = []
            for item in evidence:
                if "mail_import_session_id" not in item:
                    continue
                mail_evidence.append(item)
                citations.append(_citation_for_snippet(item))
            payload = {
                "status": status,
                **({"presentation_truncated": True} if header_groups_truncated else {}),
                "mail_import_session_id": selector,
                "query_hash": sha256_json(query_text),
                "evidence_snippets": mail_evidence,
                **({"query_agent": query_agent} if native_locator is not None else {}),
                "citations": citations,
                "warnings": sorted(set(
                    [*double_check.warnings]
                    + (["mail_evidence_no_verified_citations"] if not citations else [])
                )),
                "requested_field_coverage": coverage_payload if requested_fields else None,
            }
            if payload["requested_field_coverage"] is None:
                payload.pop("requested_field_coverage")
            return _admit_source_model_envelope(
                payload, staged_items=double_check.evidence, deferred_items=presentation_deferred,
                limit=max(0, limit - source_budget["evidence"]), deadline=presentation_deadline,
                selection_hits=selection_hits, overflow_hashes=overflow_hashes,
            )
        payload = {
            "status": status,
            **({"presentation_truncated": True} if header_groups_truncated else {}),
            "answer": {
                "status": status,
                "text": "Source-backed evidence is available." if evidence else "",
                "answer_hash": sha256_json(recovery),
                "citation_count": len(evidence),
            },
            "evidence": evidence,
            "citations": recovery["citation_hashes"],
            "query_agent": query_agent,
            "graph_hits": {"count": 0},
            "canonical_kg": False,
            "deterministic_exact": False,
            "exact_result": None,
            "redaction_counts": {
                "redacted_value_count": sum(
                    item.get("content_redacted") is True for item in evidence
                )
            },
            "coverage": {
                "status": "incomplete",
                "scope": "declared_completed_ingestion_jobs",
                "reason": "retrieval_projection_unavailable",
                **(dict(coverage) if isinstance(coverage, Mapping) else {}),
            },
        }
        return _admit_source_model_envelope(
            payload, staged_items=double_check.evidence, deferred_items=presentation_deferred,
            limit=max(0, limit - source_budget["evidence"]), deadline=presentation_deadline,
                selection_hits=selection_hits, overflow_hashes=overflow_hashes,
        )

    handler.authorized_capability_summary = capabilities
    handler.reviewed_annotation_catalog = annotation_catalog
    handler.reviewed_annotation_catalog_for_query = lambda user_text: issue56_reviewed_annotation_catalog(
        revision, user_text=user_text)
    handler._issue56_allowed_relation_types = ()
    return handler


def _authorized_runtime_source_families(session: Any) -> tuple[str, ...]:
    """Use the same authorized family derivation as runtime query validation."""

    index = getattr(session, "index", None)
    runtime_store = getattr(index, "_runtime_store", None)
    runtime_store_seal = getattr(index, "_runtime_store_seal", None)
    # A lightweight test seam may expose Mock storage with a string-looking
    # seal.  It is not an indexed revision and must not be reopened merely to
    # build the public capability summary.  Real indexed stores use the
    # governed metadata path below.
    if (
        runtime_store is not None
        and type(runtime_store).__module__ == "unittest.mock"
    ):
        return ()
    if runtime_store is not None and not (
        isinstance(runtime_store_seal, str) and runtime_store_seal
    ):
        # Lightweight contract seams may carry a mock index without a sealed
        # storage revision.  Do not reopen it merely to build diagnostics;
        # a real indexed session always has a string seal and follows the
        # governed metadata path below.
        return ()
    families = tuple(sorted(set(_semantic_session_source_families(session))))
    if not families:
        raise ContractValidationError("stored source-family binding is unavailable")
    return families


def _reopen_indexed_projection(
    revision: Issue56IngestionRevision,
) -> tuple[Any | None, bool]:
    """Return a usable projection manifest and whether an indexed projection failed.

    The source reader is an independently authorized revision boundary.  A
    failed projection reopen therefore becomes a source-start route when that
    reader is present; callers must not turn a projection error into a source
    denial or an inline rebuild.
    """

    session = revision.session
    index = getattr(session, "index", None)
    runtime_store = getattr(index, "_runtime_store", None)
    if runtime_store is None:
        return None, False
    expected_seal = getattr(index, "_runtime_store_seal", None)
    if not isinstance(expected_seal, str) or not expected_seal.strip():
        return None, True
    try:
        manifest = runtime_store.reopen(expected_seal)
        if not isinstance(manifest, Mapping):
            return None, True
        view_metadata = manifest.get("view_metadata")
        session_metadata = (
            view_metadata.get("session")
            if isinstance(view_metadata, Mapping)
            else None
        )
        crosswalk_metadata = (
            view_metadata.get("crosswalk")
            if isinstance(view_metadata, Mapping)
            else None
        )
        counts = manifest.get("counts")
        if not (
            isinstance(session_metadata, Mapping)
            and isinstance(crosswalk_metadata, Mapping)
            and isinstance(counts, Mapping)
            and isinstance(manifest.get("relation_types"), Sequence)
            and not isinstance(manifest.get("relation_types"), (str, bytes))
            and session_metadata.get("source_session_binding_fingerprint")
            == getattr(session, "source_session_binding_fingerprint", None)
            and crosswalk_metadata.get("authorized_evidence_count")
            == counts.get("helper")
            and _is_sha256(session_metadata.get("provider_scope_fingerprint"))
        ):
            return None, True
    except Exception:
        # The exception itself is private storage detail.  The public route is
        # the independently validated source fallback below.
        return None, True
    return manifest, False


def build_issue56_production_semantic_retrieval_handler(
    *,
    query_agent_planner: AdaptiveQueryPlanner | None = None,
    ingestion_revision: Issue56IngestionRevision | None = None,
    _loaded_source: Any | None = None,
) -> Callable[..., dict[str, Any]]:
    """Build the opt-in production handler over the approved sealed source."""

    if _loaded_source is not None and ingestion_revision is not None:
        raise ContractValidationError(
            "loaded sealed source cannot be combined with ingestion revision"
        )
    if (
        ingestion_revision is not None
        and ingestion_revision.session is None
        and ingestion_revision.authorized_source is not None
    ):
        return _build_source_start_semantic_handler(
            ingestion_revision, mail_tool=False,
        )
    exact_cell_lookup: _IngestionExactCellLookup | None = None
    indexed_store = (
        getattr(getattr(ingestion_revision.session, "index", None), "_runtime_store", None)
        if ingestion_revision is not None and ingestion_revision.session is not None
        else None
    )
    indexed_manifest: Mapping[str, Any] | None = None
    indexed_projection_failed = False
    if ingestion_revision is not None and ingestion_revision.session is not None:
        indexed_manifest, indexed_projection_failed = _reopen_indexed_projection(
            ingestion_revision
        )
    source_records = (
        ingestion_revision.source_records
        if ingestion_revision is not None
        else None
    )
    if indexed_store is not None and indexed_projection_failed:
        if (
            ingestion_revision is not None
            and ingestion_revision.authorized_source is not None
            and source_records is not None
        ):
            return _build_source_start_semantic_handler(
                ingestion_revision,
                mail_tool=False,
            )
        raise ContractValidationError("retrieval projection is unavailable")
    if indexed_store is not None and source_records is None:
        raise ContractValidationError("indexed ingestion source reader is unavailable")
    if ingestion_revision is None:
        loaded = (
            _loaded_source
            if _loaded_source is not None
            else _load_approved_sealed_source(
                include_participant_authorization_observations=True
            )
        )
        safe_binding = _validated_owner_safe_binding(
            loaded.safe_binding,
            source_session_binding_fingerprint=(
                loaded.session.source_session_binding_fingerprint
            ),
        )
        providers = _build_mail_source_occurrence_providers(
            loaded,
            safe_binding=safe_binding,
        )
        source_records = _LoadedSealedSourceRecords(loaded)
    else:
        loaded = ingestion_revision
        exact_cell_lookup = (
            _IngestionExactCellLookup(loaded)
            if loaded.exact_lookup_manifest
            else None
        )
        providers = (
            () if indexed_store is not None else _build_ingestion_source_occurrence_providers(
                loaded.session, include_table_providers=exact_cell_lookup is None,
            )
        )
    session = (
        loaded.session
        if (
            exact_cell_lookup is not None
            or indexed_store is not None
        )
        else attach_authorized_source_occurrence_providers(
            loaded.session,
            providers,
        )
    )
    provider_scope_fingerprint = (
        indexed_manifest["view_metadata"]["session"].get("provider_scope_fingerprint")
        if indexed_manifest is not None else authorized_source_occurrence_scope_fingerprint(
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        source_scope_ids=session.authorized_source_scope_ids,
        authorized_observation_hashes=session.authorized_observation_hashes,
        source_session_binding_fingerprint=(
            session.source_session_binding_fingerprint
        ),
        )
    )
    if not _is_sha256(provider_scope_fingerprint):
        raise ContractValidationError("production provider scope seal is unavailable")
    graph_view = loaded.effective_graph_view
    text_source_authorized = (
        session.authorized_source is not None
        and session.authorized_source.authorizes_source_kind(
            AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND
        )
    )
    text_only_source = (
        session.authorized_source is not None
        and session.authorized_source.source_kind
        == AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND
        and session.authorized_source.authorized_source_kinds
        == (AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,)
    )
    if indexed_manifest is not None:
        relation_types = tuple(indexed_manifest["relation_types"])
        def relation_for_hash(edge_hash: str) -> str | None:
            edge = indexed_store.edge_for_hash(edge_hash)
            return None if edge is None else edge.relation_type
        relation_by_edge_hash = _KeyedIngestionLookup(relation_for_hash)
    else:
        relation_types = tuple(sorted({edge.relation_type for edge in graph_view.visible_edges}))
        relation_by_edge_hash = {}
        for edge in graph_view.visible_edges:
            edge_hash = sha256_json(edge.edge_id)
            if edge_hash in relation_by_edge_hash:
                raise ContractValidationError("production graph edge binding is ambiguous")
            relation_by_edge_hash[edge_hash] = edge.relation_type
    if (
        session.requester_user_id != APPROVER_ACTOR
        or session.workspace_id != WORKSPACE_ID
        or graph_view.requester_user_id != APPROVER_ACTOR
        or (
            not relation_types
            and not (
                ingestion_revision is not None
                and text_only_source
                and not graph_view.visible_edges
            )
        )
    ):
        raise ContractValidationError("production sealed source binding is invalid")
    if indexed_manifest is None:
        _validate_production_session_lineages(session)
    elif (
        indexed_manifest["view_metadata"]["session"]["source_session_binding_fingerprint"]
        != session.source_session_binding_fingerprint
        or indexed_manifest["view_metadata"]["crosswalk"]["authorized_evidence_count"]
        != indexed_manifest["counts"]["helper"]
    ):
        raise ContractValidationError("production indexed lineage seal mismatch")
    candidate_ledger = (
        None
        if exact_cell_lookup is not None or indexed_store is not None
        else _build_candidate_table_ledger(session)
    )
    candidate_lookup = (None if candidate_ledger is None else build_authorized_candidate_table_lookup(
        session=session, ledger=candidate_ledger))
    capability_fields: dict[tuple[str, str, str], dict[str, Any]] = {}
    capability_providers = []
    for provider in providers:
        source_family = (
            "attachment_table" if (
                provider.filter_slot_policy == "combined_present_intersection_v1"
                and provider.resource_kind != "mail_inline_table_row_occurrence"
            )
            else "mail"
        )
        capability_providers.append({
            "provider_fingerprint": provider.provider_fingerprint,
            "source_family": source_family,
            "filter_slot_policy": provider.filter_slot_policy,
            "resource_kind": provider.resource_kind,
            "normalized_field": provider.normalized_field,
            "source_provided_occurrence_count": sum(
                item.structure_status == "source_provided"
                for item in provider.occurrences
            ),
            "candidate_only_occurrence_count": sum(
                item.structure_status == "candidate_only"
                for item in provider.occurrences
            ),
        })
        for item in provider.occurrences:
            for (
                column_hash,
                candidate_hash,
                _value_hash,
                field,
                _value,
                _citation_hash,
                _lineage_fingerprint,
            ) in item.structured_column_bindings:
                safe_field, redacted = redact_public_raw_references(field)
                entry = capability_fields.setdefault(
                    (safe_field[:120], column_hash, str(item.structure_status)),
                    {
                        "candidate_hashes": set(),
                        "item_hashes": set(),
                        "label_redacted": False,
                    },
                )
                entry["candidate_hashes"].add(candidate_hash)
                entry["item_hashes"].add(item.item_hash)
                entry["label_redacted"] = entry["label_redacted"] or bool(redacted)
    if exact_cell_lookup is not None:
        capability_providers.extend(exact_cell_lookup.capability_providers)
    all_capability_fields = [
        {
            "field": label,
            "field_hash": column_hash,
            "candidate_hashes": sorted(entry["candidate_hashes"]),
            "structure_status": structure_status,
            "authorized_occurrence_count": len(entry["item_hashes"]),
            "label_redacted": entry["label_redacted"],
        }
        for (
            label,
            column_hash,
            structure_status,
        ), entry in sorted(capability_fields.items())
    ]
    if exact_cell_lookup is not None:
        all_capability_fields.extend(exact_cell_lookup.capability_fields)
        all_capability_fields = sorted(
            {
                (
                    item["field"],
                    item["field_hash"],
                    item["structure_status"],
                ): item
                for item in all_capability_fields
            }.values(),
            key=lambda item: (
                item["field"],
                item["field_hash"],
                item["structure_status"],
            ),
        )
    authorized_runtime_source_families = _authorized_runtime_source_families(session)
    capability_core = {
        "artifact_id": "formowl_authorized_query_capability_summary_v1",
        **({"ingestion_coverage": dict(ingestion_revision.safe_binding)}
           if ingestion_revision is not None else {}),
        "identity_scope_mode": IDENTITY_SCOPE_MODE,
        "workspace_id": session.workspace_id,
        "source_session_binding_fingerprint": (
            session.source_session_binding_fingerprint
        ),
        "listing_status": (
            "incomplete" if indexed_store is not None
            else ("complete" if len(all_capability_fields) <= 128 else "truncated")
        ),
        "projection_field_count": len(all_capability_fields),
        "returned_projection_field_count": min(len(all_capability_fields), 128),
        "projection_fields": all_capability_fields[:128],
        "source_families": list(authorized_runtime_source_families),
        "query_classes": list(SEMANTIC_QUERY_CLASSES),
        "maximum_claim_strength_by_query_class": dict(
            SEMANTIC_CLAIM_STRENGTH_BY_CLASS
        ),
        "providers": sorted(
            capability_providers,
            key=lambda item: item["provider_fingerprint"],
        ),
        "query_contract": {
            "filter_value_candidate_origins": [
                "user_request",
                "planner_semantic_expansion",
            ],
            "candidate_filter_value_requires_exact_authorized_source_match": True,
            "projection_labels_must_match_authorized_fields": True,
            "structured_table_query_supported": True,
            "structured_table_query_contract": {
                "filters": {
                    "minimum_count": 1,
                    "maximum_count": 4,
                    "field": "exact_authorized_source_provided_label",
                    "value": (
                        "exact_authorized_source_value_from_user_or_candidate_expansion"
                    ),
                },
                "projection_fields": {
                    "minimum_count": 1,
                    "maximum_count": 8,
                    "labels": "exact_authorized_source_provided_labels",
                },
                "free_text_directional_particle_required": False,
            },
            "binding_order": [
                "user_request_filter_value",
                "single_directional_particle",
                "authorized_source_provided_projection_field",
            ],
            "directional_particle_count": 1,
            "supported_directional_particle_token": "的",
            "projection_connector_tokens": ["以及", "與", "和", "跟", "還有"],
            "supported_neutral_query_template": "{filter_value}的{projection_field}",
            "candidate_only_is_deterministic_exact": False,
        },
    }
    authorized_capabilities = {
        **capability_core,
        "capability_fingerprint": sha256_json(capability_core),
    }
    validate_public_gateway_payload(authorized_capabilities)
    if indexed_store is not None:
        def observations_for_hash(value: str) -> tuple[Observation, ...] | None:
            observation = source_records.observation_for_hash(value)
            return None if observation is None else (observation,)
        observations_by_hash = _KeyedIngestionLookup(observations_for_hash)
        lineage_by_observation_id = _KeyedIngestionLookup(
            lambda key: (
                source_records.lineage(key)
                if indexed_store.get_helper(key) is not None else None
            )
        )
    else:
        observation_by_id = {item.observation_id: item for item in session.authorized_observations}
        observations_by_hash = {}
        for observation_id, observation_hash in session.authorized_observation_hashes:
            if observation_id in observation_by_id:
                observations_by_hash.setdefault(observation_hash, []).append(
                    observation_by_id[observation_id]
                )
        lineage_by_observation_id = {
            item.source_observation_id: item for item in session.occurrence_lineages
        }
    text_revision_binding: dict[str, str] | None = None
    if ingestion_revision is not None and text_source_authorized:
        authority_fingerprint = ingestion_revision.safe_binding.get(
            "source_authority_fingerprint"
        )
        if (
            not _is_sha256(authority_fingerprint)
            or authority_fingerprint != session.source_authority_fingerprint
            or not _is_sha256(session.source_session_binding_fingerprint)
        ):
            raise ContractValidationError(
                "production text revision binding is invalid"
            )
        text_revision_binding = {
            "source_authority_fingerprint": authority_fingerprint,
            "source_session_binding_fingerprint": (
                session.source_session_binding_fingerprint
            ),
        }

    def project_observation_evidence(
        observation: Observation,
        *,
        citation_hash: str,
        lineage: Any,
        focus_terms: Sequence[str] = (),
    ) -> tuple[dict[str, Any], int] | None:
        source_text = observation.text or observation.caption or ""
        if not source_text:
            return None
        snippet, redacted = redact_public_raw_references(source_text)
        # Keep the existing 400-character bound, but do not discard a requested
        # field merely because it follows a long preamble. Select one contiguous
        # source excerpt, never synthesized text or evidence of field coverage.
        start = 0
        if len(snippet) > 400:
            for term in focus_terms:
                match = re.search(re.escape(term.replace("_", " ")), snippet, re.IGNORECASE)
                if match is not None:
                    start = max(0, min(match.start() - 80, len(snippet) - 400))
                    break
        evidence_item = {
            "snippet": snippet[start:start + 400],
            "citation_hash": citation_hash,
            "occurrence_lineage_fingerprint": lineage.lineage_fingerprint,
        }
        if isinstance(lineage, TextDocumentOccurrenceLineage):
            location = observation.location
            if (
                text_revision_binding is None
                or not session.authorized_source.authorizes_source_kind(
                    AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND
                )
                or observation.modality != "text"
                or observation.observation_type not in {"heading", "paragraph"}
                or lineage.source_observation_id != observation.observation_id
                or lineage.asset_id != observation.asset_id
                or lineage.extractor_run_id != observation.extractor_run_id
                or type(location.get("line_start")) is not int
                or type(location.get("line_end")) is not int
                or location.get("line_start") != lineage.line_start
                or location.get("line_end") != lineage.line_end
            ):
                raise ContractValidationError(
                    "production text citation locator binding is invalid"
                )
            evidence_item.update({
                "document_locator": {
                    "block_type": observation.observation_type,
                    "asset_id": lineage.asset_id,
                    "extractor_run_id": lineage.extractor_run_id,
                    "line_start": lineage.line_start,
                    "line_end": lineage.line_end,
                },
                "revision_binding": text_revision_binding,
            })
        if redacted:
            evidence_item["content_redacted"] = True
        return evidence_item, redacted

    def project_evidence(
        result: Any,
        *,
        limit: int,
        additional_observations_by_hash: Mapping[
            str, tuple[Observation, ...]
        ] = MappingProxyType({}),
        additional_lineages_by_observation_id: Mapping[
            str, Any
        ] = MappingProxyType({}),
    ) -> tuple[list[dict[str, Any]], int]:
        hashes = [*result.answer_citation_hashes,
                  *(score.source_observation_hash for score in result.scores)]
        if result.exact_result is not None:
            for item in result.exact_result.items:
                hashes.extend(item.cited_observation_hashes)
                hashes.extend(value[0] for value in item.governed_references)
        evidence: list[dict[str, Any]] = []
        redaction_count = 0
        for citation_hash in dict.fromkeys(hashes):
            bound_observations = (
                observations_by_hash.get(citation_hash)
                or additional_observations_by_hash.get(citation_hash)
            )
            if not bound_observations:
                raise ContractValidationError("production evidence authorization binding is invalid")
            for observation in sorted(
                bound_observations,
                key=lambda item: item.observation_id,
            ):
                lineage = (
                    lineage_by_observation_id.get(observation.observation_id)
                    or additional_lineages_by_observation_id.get(
                        observation.observation_id
                    )
                )
                if lineage is None:
                    raise ContractValidationError(
                        "production evidence lineage binding is invalid"
                    )
                projected = project_observation_evidence(
                    observation,
                    citation_hash=citation_hash,
                    lineage=lineage,
                )
                if projected is None:
                    continue
                item, redacted = projected
                evidence.append(item)
                redaction_count += redacted
                if len(evidence) == limit:
                    return evidence, redaction_count
        return evidence, redaction_count

    def project_query_agent_context(
        results: tuple[Any, ...],
        payload: dict[str, Any],
        *,
        additional_observations_by_hash: Mapping[
            str, tuple[Observation, ...]
        ] = MappingProxyType({}),
        additional_lineages_by_observation_id: Mapping[
            str, Any
        ] = MappingProxyType({}),
    ) -> dict[str, Any]:
        contexts = []
        citations = set(payload["context_bundle"]["citation_hashes"])
        lineages = set(payload["context_bundle"]["lineage_fingerprints"])
        redaction_count = 0
        for result in results:
            evidence, redacted = project_evidence(
                result,
                limit=4,
                additional_observations_by_hash=(
                    additional_observations_by_hash
                ),
                additional_lineages_by_observation_id=(
                    additional_lineages_by_observation_id
                ),
            )
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

    def validate_projection(payload: dict[str, Any]) -> None:
        if ingestion_revision is not None:
            payload["coverage"] = {
                "status": "incomplete",
                "scope": "declared_completed_ingestion_jobs",
                "reason": "upstream_source_completeness_not_certified",
                **dict(ingestion_revision.safe_binding.get("extraction_coverage", {})),
            }
        validate_public_gateway_payload(payload)

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
            "table_query",
            "request_contract",
            "required_terms",
            "field_query_hints",
        }:
            raise ContractValidationError("production semantic arguments are invalid")
        if (
            arguments["requester_user_id"] != session.requester_user_id
            or arguments["workspace_id"] != session.workspace_id
            or not isinstance(arguments["session_id"], str)
            or not arguments["session_id"]
        ):
            raise ContractValidationError("production semantic actor binding mismatch")
        from formowl_mail.human_uat_orchestrator import validated_field_query_hints

        field_query_hints = validated_field_query_hints(
            arguments, available_source_families=authorized_capabilities["source_families"],
        )
        if "native_locator" in (arguments.get("request_contract") or {}):
            raise ContractValidationError("native attachment page requires source-start handler")
        placement = _request_term_placement(arguments)

        # Provider planning is allowed to omit the optional structured selector,
        # but an identifier-plus-field evidence lookup still has a deterministic
        # server-owned path.  Use the sealed exact-cell lookup before graph/top-k
        # execution; a miss falls through to the existing bounded recovery path.
        # This keeps the provider from deciding whether a native row is exact and
        # preserves the source/permission/lineage checks in the exact executor.
        request_contract_input = arguments.get("request_contract")
        automatic_exact_payload: dict[str, Any] | None = None
        if (
            placement is None
            and exact_cell_lookup is not None
            and isinstance(request_contract_input, Mapping)
            and request_contract_input.get("query_class") == "evidence_lookup"
            and request_contract_input.get("requested_fields")
            and not any(arguments.get(key) is not None for key in (
                "table_query", "exact_inventory_kind", "exact_field", "cursor",
            ))
        ):
            profile = exact_cell_lookup._tokenizer_profile
            query_text = arguments["query_text"]
            query_analysis = profile.analyze(query_text)
            identifier_terms = tuple(
                span.exact_token for span in query_analysis.protected_identifiers
            )
            raw_required_terms = arguments.get("required_terms")
            if isinstance(raw_required_terms, list):
                normalized_required_terms = tuple(
                    sorted(
                        unicodedata.normalize("NFKC", term.strip()).casefold()
                        for term in raw_required_terms
                        if isinstance(term, str) and term.strip()
                    )
                )
            else:
                normalized_required_terms = ()
            if not identifier_terms:
                identifier_terms = tuple(
                    term for term in normalized_required_terms
                    if term in unicodedata.normalize("NFKC", query_text).casefold()
                    and (
                        term.isdecimal()
                        or profile.analyze(term).protected_identifiers
                    )
                )
            if identifier_terms:
                automatic_exact_payload = _execute_source_start_table(
                    ingestion_revision,
                    lookup=exact_cell_lookup,
                    arguments=arguments,
                    request_contract=request_contract_input,
                    mail_tool=False,
                    selector=None,
                    identifier_terms=identifier_terms,
                    required_terms=normalized_required_terms,
                    automatic=True,
                )
                if (
                    automatic_exact_payload.get("deterministic_exact")
                    or automatic_exact_payload.get("citations")
                ):
                    automatic_exact_payload["query_agent"] = {
                        **dict(automatic_exact_payload.get("query_agent", {})),
                        "authorized_capability_summary": authorized_capabilities,
                    }
                    validate_projection(automatic_exact_payload)
                    return automatic_exact_payload
        request_session = session
        request_providers = providers
        request_observations_by_hash: Mapping[
            str, tuple[Observation, ...]
        ] = MappingProxyType({})
        request_lineages_by_observation_id: Mapping[
            str, Any
        ] = MappingProxyType({})
        request_candidate_session = request_session
        request_candidate_lookup = candidate_lookup
        if placement is None and exact_cell_lookup is not None:
            provider_batch = exact_cell_lookup.providers_for_request(
                query_text=arguments["query_text"],
                table_query=arguments.get("table_query"),
                authorized_scope_fingerprint=provider_scope_fingerprint,
            )
            request_providers = (*providers, *provider_batch.providers)
            request_session = attach_authorized_source_occurrence_providers(
                session,
                request_providers,
                additional_authorized_reference_pairs=(
                    provider_batch.authorized_reference_pairs
                ),
            )
            request_observations_by_hash = (
                provider_batch.observations_by_hash
            )
            request_lineages_by_observation_id = (
                provider_batch.lineages_by_observation_id
            )
            candidate_observations = {
                observation.observation_id: observation
                for bound_observations in request_observations_by_hash.values()
                for observation in bound_observations
            }
            if candidate_observations:
                candidate_hashes = tuple(
                    sorted(
                        (
                            observation.observation_id,
                            sha256_json(observation.to_dict()),
                        )
                        for observation in candidate_observations.values()
                    )
                )
                candidate_lineages = tuple(
                    sorted(
                        request_lineages_by_observation_id.values(),
                        key=lambda item: item.source_observation_id,
                    )
                )
                request_candidate_session = replace(
                    session,
                    authorized_observations=tuple(
                        sorted(
                            candidate_observations.values(),
                            key=lambda item: item.observation_id,
                        )
                    ),
                    authorized_observation_hashes=candidate_hashes,
                    occurrence_lineages=candidate_lineages,
                )
                request_candidate_ledger = _build_candidate_table_ledger(
                    request_candidate_session
                )
                if request_candidate_ledger is not None:
                    request_candidate_lookup = (
                        build_authorized_candidate_table_lookup(
                            session=request_candidate_session,
                            ledger=request_candidate_ledger,
                        )
                    )
        result, successful_results, query_agent_payload = execute_bounded_adaptive_query(
            session=request_session,
            query_text=arguments["query_text"],
            table_query=arguments.get("table_query"),
            request_contract=arguments.get("request_contract"),
            effective_graph_view=graph_view,
            allowed_relation_types=relation_types,
            exact_inventory_kind=arguments.get("exact_inventory_kind"),
            exact_field=arguments.get("exact_field"),
            page_size=arguments.get("page_size", 20),
            cursor=arguments.get("cursor"),
            planner=query_agent_planner,
        )
        query_agent_payload = project_query_agent_context(
            successful_results,
            query_agent_payload,
            additional_observations_by_hash=request_observations_by_hash,
            additional_lineages_by_observation_id=(
                request_lineages_by_observation_id
            ),
        )
        query_agent_payload = {
            **query_agent_payload,
            "authorized_capability_summary": authorized_capabilities,
        }
        external_replan = query_agent_payload.get("external_replan")
        unsupported_requires_external_replan = (
            query_agent_payload["status"] == "unsupported"
            and isinstance(external_replan, Mapping)
            and external_replan.get("status") in {"available", "required"}
            and not query_agent_payload["context_bundle"]["citation_hashes"]
        )
        public_replan_status = (
            "replan_required"
            if query_agent_payload["status"] == "replan_required"
            or unsupported_requires_external_replan
            else None
        )
        request_contract_summary = query_agent_payload.get("request_contract")
        requested_source_families = (
            request_contract_summary.get("source_family_scope", ())
            if isinstance(request_contract_summary, Mapping)
            else ()
        )
        candidate_table_requested = (
            request_contract_summary is None
            or any(
                family in {"mail", "attachment_table"}
                for family in requested_source_families
            )
        )
        candidate = (
            interpret_authorized_candidate_table_query(
                session=request_candidate_session,
                query_text=arguments["query_text"],
                lookup=request_candidate_lookup,
            )
            if (
                request_candidate_lookup is not None
                and candidate_table_requested
                and arguments.get("table_query") is None
                and arguments.get("exact_inventory_kind") is None
                and arguments.get("exact_field") is None
                and arguments.get("cursor") is None
            )
            else None
        )
        if placement is not None:
            query_agent_payload = _placement_initial_context(query_agent_payload)
        if candidate is not None and placement is None:
            candidate_payload = {
                **candidate.to_safe_dict(),
                "structure_status": "candidate_only",
            }
            citation_hashes = [
                item["observation_hash"]
                for item in candidate_payload["governed_citations"]
            ]
            if len(citation_hashes) != 4 or len(set(citation_hashes)) != 4:
                raise ContractValidationError(
                    "production candidate citation binding is invalid"
                )
            payload = {
                "status": public_replan_status or candidate.status,
                "answer": {
                    "status": candidate.status,
                    "text": f"{candidate.header}: {candidate.value}",
                    "header": candidate.header,
                    "value": candidate.value,
                    "answer_hash": sha256_json(candidate_payload),
                    "source_result_fingerprint": candidate.result_fingerprint,
                    "citation_count": 4,
                },
                "candidate_interpretation": candidate_payload,
                "query_agent": query_agent_payload,
                "citations": citation_hashes,
                "evidence": [],
                "graph_hits": {
                    "count": result.graph_path_count if result is not None else 0
                },
                "canonical_kg": False,
                "deterministic_exact": False,
                "exact_result": None,
                "redaction_counts": {"redacted_value_count": 0},
            }
            validate_projection(payload)
            return payload
        if result is None or (placement is not None and result.exact_result is not None):
            payload = {
                "status": public_replan_status or "replan_required",
                "query_agent": query_agent_payload,
                "citations": [],
                "evidence": [],
                "graph_hits": {"count": 0},
                "canonical_kg": False,
                "deterministic_exact": False,
                "exact_result": None,
                "redaction_counts": {"redacted_value_count": 0},
            }
            validate_projection(payload)
            return payload
        exact_result = result.exact_result
        request_contract_input = arguments.get("request_contract")
        requested_fields = (
            tuple(request_contract_input.get("requested_fields", ()))
            if isinstance(request_contract_input, Mapping)
            else ()
        )
        exact_inventory_kind = arguments.get("exact_inventory_kind")
        if exact_result is not None and (
            exact_inventory_kind or arguments.get("exact_field") or arguments.get("cursor")
        ):
            # A validated explicitly selected inventory is itself deliverable.
            # Keep repair advice in query_agent, not as a replacement for its
            # incomplete/complete exact-result status and usable rows.
            public_replan_status = None
        if (
            result.status == "incomplete" and result.claim_strength == "no_claim"
            and result.query_class == "evidence_lookup" and exact_result is None
            and result.index_fingerprint and result.materialized_candidate_count > 0
            and not result.answer_citation_hashes
        ):
            # A validated no-claim lookup miss is not a transport/planner
            # failure. Retain its incomplete boundary and separate repair hint.
            public_replan_status = None
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
        requested_evidence_cap = arguments.get("page_size", 20)
        if type(requested_evidence_cap) is not int or requested_evidence_cap < 1:
            raise ContractValidationError("production document evidence limit is invalid")
        header_groups_truncated = False
        evidence, redaction_count = project_evidence(
            result,
            limit=(
                min(10, requested_evidence_cap)
                if result.query_class == "evidence_lookup"
                else 10
            ),
            additional_observations_by_hash=request_observations_by_hash,
            additional_lineages_by_observation_id=(
                request_lineages_by_observation_id
            ),
        )
        supported_requested_fields = source_evidence_supported_requested_fields(
            requested_fields,
            exact_result=exact_result,
            answer_citation_hashes=tuple(item["citation_hash"] for item in evidence),
            verified_citation_lineages=tuple(
                (item["citation_hash"], item["occurrence_lineage_fingerprint"])
                for item in evidence
            ),
        )
        initial_evidence_count = len(evidence)
        source_recovery: dict[str, Any] | None = None
        requested_source_families = (
            request_contract_summary.get("source_family_scope", ())
            if isinstance(request_contract_summary, Mapping)
            else ()
        )
        requested_source_family_set = (
            set(requested_source_families)
            if isinstance(requested_source_families, (list, tuple))
            and all(isinstance(family, str) for family in requested_source_families)
            else set()
        )
        request_query_class = (
            request_contract_summary.get("query_class", result.query_class)
            if isinstance(request_contract_summary, Mapping)
            else result.query_class
        )
        recovery_execution_valid = _graph_source_recovery_is_eligible(
            arguments=arguments,
            request_query_class=request_query_class,
            result=result,
            request_contract_summary=request_contract_summary,
            query_agent_payload=query_agent_payload,
            requested_fields=requested_fields,
            supported_requested_fields=supported_requested_fields,
        )
        if placement is not None:
            evidence = []  # No initial projection proves the private occurrence predicate.
        mail_selector_ids: tuple[str, ...] = ()
        if "mail" in requested_source_family_set and source_records is not None:
            raw_mail_selector_ids = getattr(
                source_records,
                "authorized_mail_import_session_ids",
                (),
            )
            if (
                not isinstance(raw_mail_selector_ids, Sequence)
                or isinstance(raw_mail_selector_ids, (str, bytes))
                or len(raw_mail_selector_ids) > 128
                or any(not isinstance(value, str) or not value.strip()
                       for value in raw_mail_selector_ids)
            ):
                raise ContractValidationError(
                    "production mail source selector binding is invalid"
                )
            mail_selector_ids = tuple(sorted(set(raw_mail_selector_ids)))
        mail_recheck_allowed = (
            recovery_execution_valid
            and "exact_query_requires_structured_binding"
            not in getattr(result, "warnings", ())
            and session.authorized_source is not None
            and session.authorized_source.authorizes_source_kind(
                AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
            )
            and bool(mail_selector_ids)
        )
        recovery_source_families: list[str] = []
        if (
            recovery_execution_valid
            and "document_text" in requested_source_family_set and text_source_authorized
        ):
            recovery_source_families.append("document_text")
        if "mail" in requested_source_family_set and mail_recheck_allowed:
            recovery_source_families.append("mail")
        if source_records is not None and recovery_source_families:
            source_reader = getattr(
                source_records,
                "scan_authorized_observations",
                None,
            )
            authorized_source = session.authorized_source
            authorized_scope_ids = tuple(authorized_source.source_scope_ids)
            tokenizer_profile = session.index._runtime_components.tokenizer_profile
            query_terms: set[str] = set()
            protected_query_tokens: set[str] = set()
            active_source_family: str | None = None
            active_mail_selector: str | None = None
            raw_required_terms = arguments.get("required_terms")
            if raw_required_terms is None:
                required_terms: tuple[str, ...] = ()
            elif (
                not isinstance(raw_required_terms, list)
                or not 1 <= len(raw_required_terms) <= 8
                or any(
                    not isinstance(term, str)
                    or not term.strip()
                    or len(term) > 80
                    for term in raw_required_terms
                )
            ):
                raise ContractValidationError(
                    "production evidence required terms are invalid"
                )
            else:
                required_terms = tuple(
                    sorted(
                        unicodedata.normalize("NFKC", term.strip()).casefold()
                        for term in raw_required_terms
                    )
                )
                if not required_terms or len(set(required_terms)) != len(required_terms):
                    raise ContractValidationError(
                        "production evidence required terms are invalid"
                    )
            extraction_coverage = ingestion_revision.safe_binding.get(
                "extraction_coverage",
                {},
            )
            sealed_coverage_complete = (
                isinstance(extraction_coverage, Mapping)
                and extraction_coverage.get("source_completeness_certified")
                is True
                and not ingestion_revision.safe_binding.get(
                    "bounded_canary_candidate_count"
                )
            )

            recovery_mail_parents: dict[tuple[str, str, str, str], Observation] = {}

            def begin_document_source_projection(deadline: float) -> None:
                nonlocal query_terms, protected_query_tokens
                check_source_evidence_deadline(deadline)
                query_analysis = tokenizer_profile.analyze(arguments["query_text"])
                check_source_evidence_deadline(deadline)
                query_terms = set(query_analysis.tokens)
                protected_query_tokens = {
                    span.exact_token
                    for span in query_analysis.protected_identifiers
                }
                # The family dispatcher does not directly close over query_terms.
                # Bind the normalized hint explicitly for the shared sealed reader;
                # shortlist hashes still require the same authority and matcher checks.
                lookup_terms: set[str] = set()
                for term in (placement.child_terms if placement is not None else required_terms):
                    check_source_evidence_deadline(deadline)
                    lookup_terms.update(tokenizer_profile.analyze(term).tokens)
                project_source_observation.source_lookup_terms = tuple(sorted(
                    lookup_terms if required_terms else query_terms
                ))
                preferred_terms: set[str] = set()
                for field in (*requested_fields, *(hint["text"] for hint in field_query_hints)) if required_terms else ():
                    check_source_evidence_deadline(deadline)
                    preferred_terms.update(tokenizer_profile.analyze(field).tokens)
                project_source_observation.source_lookup_preferred_terms = tuple(sorted(preferred_terms))
                check_source_evidence_deadline(deadline)

            def project_document_source_observation(
                observation: Observation,
                source_scope_id: str,
                deadline: float,
            ) -> tuple[str, dict[str, Any]] | None:
                check_source_evidence_deadline(deadline)
                if (
                    not isinstance(source_scope_id, str)
                    or source_scope_id not in authorized_scope_ids
                    or observation.modality != "text"
                    or observation.observation_type not in {"heading", "paragraph"}
                    or not authorized_permission_scope_matches(
                        observation.permission_scope,
                        authorized_source=authorized_source,
                        source_kind=AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,
                    )
                    or to_plain(observation.permission_scope).get("scope_id")
                    != source_scope_id
                ):
                    raise ContractValidationError(
                        "production document source scope binding is invalid"
                    )
                observation_hash = sha256_json(observation.to_dict())
                # The sealed reader checked the reference hash, completed job,
                # asset, permission and revision before invoking this callback.
                # A canary index is not the source authority. Requiring an
                # indexed helper here would exclude the evidence being recovered.
                reader_lineage = source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=authorized_source,
                )
                source_text = observation.text or observation.caption or ""
                if not source_text:
                    return None
                if required_terms:
                    normalized_source_text = (
                        unicodedata.normalize("NFKC", source_text).casefold()
                    )
                    if not all(term in normalized_source_text for term in required_terms):
                        return None
                    source_tokens: set[str] | None = None
                else:
                    source_analysis = tokenizer_profile.analyze(source_text)
                    check_source_evidence_deadline(deadline)
                    source_tokens = set(source_analysis.tokens)
                    if not query_terms.intersection(source_tokens):
                        return None
                if protected_query_tokens:
                    if source_tokens is None:
                        source_analysis = tokenizer_profile.analyze(source_text)
                        check_source_evidence_deadline(deadline)
                        source_tokens = set(source_analysis.tokens)
                    if not protected_query_tokens.issubset(source_tokens):
                        return None
                projected = project_observation_evidence(
                    observation,
                    citation_hash=observation_hash,
                    lineage=reader_lineage,
                    focus_terms=(*requested_fields, *required_terms, *sorted(query_terms)),
                )
                if projected is None:
                    return None
                item, _ = projected
                item["source_scope_fingerprint"] = sha256_json(source_scope_id)
                check_source_evidence_deadline(deadline)
                return observation_hash, item

            def project_mail_source_observation(
                observation: Observation,
                source_scope_id: str,
                deadline: float,
            ) -> tuple[str, dict[str, Any]] | None:
                check_source_evidence_deadline(deadline)
                if (
                    source_scope_id != active_mail_selector
                    or source_scope_id not in mail_selector_ids
                    or observation.modality != "mail"
                    or observation.observation_type
                    not in REVISION_SOURCE_FALLBACK_OBSERVATION_TYPES
                    or not authorized_permission_scope_matches(
                        observation.permission_scope,
                        authorized_source=authorized_source,
                        source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
                    )
                ):
                    raise ContractValidationError(
                        "production mail source scope binding is invalid"
                    )
                parent_key = (source_scope_id, observation.asset_id, observation.extractor_run_id,
                              observation.location.get("message_occurrence_id"))
                if observation.observation_type == "email_message":
                    recovery_mail_parents[parent_key] = observation
                if placement is None and (
                    _source_mail_observation_match(
                        observation,
                        query_terms=query_terms,
                        required_terms=required_terms or None,
                        protected_query_tokens=protected_query_tokens,
                        tokenizer_profile=tokenizer_profile,
                        deadline_monotonic=deadline,
                    )
                    is None
                ):
                    return None
                observation_hash = sha256_json(observation.to_dict())
                lineage = source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=authorized_source,
                )
                projected = project_observation_evidence(
                    observation,
                    citation_hash=observation_hash,
                    lineage=lineage,
                    focus_terms=(*requested_fields, *required_terms, *sorted(query_terms)),
                )
                if projected is None:
                    return None
                item, _ = projected
                item["source_scope_fingerprint"] = sha256_json(source_scope_id)
                if placement is not None:
                    item = _placement_mail_group(
                        placement, observation, source_scope_id, item, source=authorized_source,
                        protected_terms=protected_query_tokens, tokenizer=tokenizer_profile,
                    )
                    if item is None:
                        return None
                else:
                    item = _mail_header_context(
                        observation, item, recovery_mail_parents.get(parent_key),
                        source=authorized_source, scope_id=source_scope_id,
                    )
                check_source_evidence_deadline(deadline)
                return observation_hash, item

            def project_source_observation(
                observation: Observation,
                source_scope_id: str,
                deadline: float,
            ) -> tuple[str, dict[str, Any]] | None:
                if active_source_family == "mail":
                    return project_mail_source_observation(
                        observation,
                        source_scope_id,
                        deadline,
                    )
                if active_source_family != "document_text":
                    raise ContractValidationError("production source family binding is invalid")
                return project_document_source_observation(
                    observation,
                    source_scope_id,
                    deadline,
                )

            warning_groups = (
                getattr(result, "warnings", ()),
                query_agent_payload.get("warnings", ()),
            )
            result_warnings = tuple(
                warning
                for group in warning_groups
                if isinstance(group, (list, tuple))
                for warning in group
                if isinstance(warning, str)
            )
            def read_authorized_source_families(**kwargs: Any) -> RevisionOwnedMailSourceScan:
                nonlocal active_source_family, active_mail_selector
                max_observations = kwargs["max_observations"]
                deadline = kwargs["deadline_monotonic"]
                scanned_observation_count = 0
                complete = True
                stop_reason: str | None = None
                core_stopped = False
                for family_index, source_family in enumerate(recovery_source_families):
                    now = time.monotonic()
                    if now >= deadline:
                        complete, stop_reason = False, "deadline"
                        break
                    remaining = max_observations - scanned_observation_count
                    if remaining <= 0:
                        complete, stop_reason = False, "observation_limit"
                        break
                    families_left = len(recovery_source_families) - family_index
                    family_deadline = now + (deadline - now) / families_left
                    family_remaining = remaining // families_left
                    selectors = mail_selector_ids if source_family == "mail" else (None,)
                    active_source_family = source_family
                    for selector_index, selector in enumerate(selectors):
                        now = time.monotonic()
                        if now >= family_deadline or family_remaining <= 0:
                            complete = False
                            stop_reason = (
                                "deadline" if now >= family_deadline else "observation_limit"
                            )
                            break
                        selectors_left = len(selectors) - selector_index
                        slice_deadline = now + (family_deadline - now) / selectors_left
                        slice_limit = family_remaining // selectors_left
                        if slice_limit <= 0:
                            complete, stop_reason = False, "observation_limit"
                            break
                        active_mail_selector = selector
                        callback_count = 0
                        slice_stopped = False

                        def consume(observation: Observation, scope: str) -> bool:
                            nonlocal callback_count, core_stopped, slice_stopped
                            if callback_count >= slice_limit or time.monotonic() >= slice_deadline:
                                slice_stopped = True
                                return False
                            callback_count += 1
                            if not kwargs["observation_callback"](observation, scope):
                                core_stopped = True
                                return False
                            return True

                        scan = source_reader(
                            source_family=source_family,
                            source_scope_ids=(
                                authorized_scope_ids if source_family == "document_text" else ()
                            ),
                            mail_import_session_id=selector,
                            max_observations=slice_limit,
                            deadline_monotonic=slice_deadline,
                            observation_callback=consume,
                        )
                        if (
                            not isinstance(scan, RevisionOwnedMailSourceScan)
                            or type(scan.scanned_observation_count) is not int
                            or not 0 <= scan.scanned_observation_count <= slice_limit
                            or type(scan.complete) is not bool
                        ):
                            raise ContractValidationError("production source scan coverage is invalid")
                        scanned_observation_count += scan.scanned_observation_count
                        family_remaining -= scan.scanned_observation_count
                        if callback_count == 0 and not slice_stopped:
                            for observation, scope in scan.observations:
                                if not consume(observation, scope):
                                    break
                        if callback_count > scan.scanned_observation_count:
                            raise ContractValidationError("production source scan count is invalid")
                        if not scan.complete or slice_stopped or time.monotonic() >= slice_deadline:
                            complete = False
                            stop_reason = scan.stop_reason or "deadline"
                        if core_stopped:
                            complete, stop_reason = False, "callback"
                            break
                    if core_stopped:
                        break
                active_source_family = active_mail_selector = None
                return RevisionOwnedMailSourceScan(
                    observations=(),
                    scanned_observation_count=scanned_observation_count,
                    complete=complete,
                    stop_reason=stop_reason,
                )

            double_check = source_evidence_double_check(
                initial_status=result.status,
                query_class=str(request_query_class),
                result_query_class=getattr(result, "query_class", None),
                initial_warnings=result_warnings,
                verified_evidence_count=initial_evidence_count,
                evidence_limit=min(10, requested_evidence_cap),
                sealed_coverage_complete=sealed_coverage_complete,
                read_source=(
                    read_authorized_source_families
                    if callable(source_reader)
                    else None
                ),
                project_observation=project_source_observation,
                begin=begin_document_source_projection,
                excluded_hashes=tuple(
                    item["citation_hash"] for item in evidence
                ),
                requested_fields=requested_fields,
                supported_requested_fields=supported_requested_fields,
            )
            recovered_evidence, header_groups_truncated = _bounded_mail_header_groups(
                double_check.evidence, limit=max(0, min(10, requested_evidence_cap) - len(evidence)),
                byte_limit=max(0, 16 * 1024 - len(json.dumps(evidence, ensure_ascii=False).encode("utf-8"))),
            )
            if header_groups_truncated:
                double_check = replace(double_check, warnings=(*double_check.warnings, "incomplete"))
            evidence.extend(recovered_evidence)
            redaction_count += sum(
                item.get("content_redacted") is True
                for item in recovered_evidence
            )
            if double_check.status is not None:
                result_status = double_check.status
            else:
                result_status = public_replan_status or result.status
            source_recovery = {
                "artifact_id": "formowl_bounded_source_recovery_v1",
                "source_family": (
                    recovery_source_families[0]
                    if len(recovery_source_families) == 1
                    else "source_neutral"
                ),
                "source_families": recovery_source_families,
                "source_family_scope": list(requested_source_families),
                "query_hash": sha256_json(arguments["query_text"]),
                "initial_status": result.status,
                "status": result_status,
                "attempted": double_check.scan is not None,
                "scan": (
                    {
                        "scanned_observation_count": (
                            double_check.scan.scanned_observation_count
                        ),
                        "complete": double_check.scan.complete,
                        "stop_reason": double_check.scan.stop_reason,
                    }
                    if double_check.scan is not None
                    else None
                ),
                "source_authority_fingerprint": (
                    session.source_authority_fingerprint
                ),
                "source_session_binding_fingerprint": (
                    session.source_session_binding_fingerprint
                ),
                "source_scope_fingerprints": sorted(
                    {
                        item["source_scope_fingerprint"]
                        for item in recovered_evidence
                    }
                ),
                "citation_hashes": sorted(
                    item["citation_hash"] for item in recovered_evidence
                ),
                "lineage_fingerprints": sorted(
                    item["occurrence_lineage_fingerprint"]
                    for item in recovered_evidence
                ),
                "evidence": recovered_evidence,
                "warnings": list(double_check.warnings),
            }
            source_recovery["recovery_fingerprint"] = sha256_json(
                source_recovery
            )
            context_bundle = {
                **query_agent_payload["context_bundle"],
                "citation_hashes": sorted(
                    set(
                        query_agent_payload["context_bundle"][
                            "citation_hashes"
                        ]
                    )
                    | set(source_recovery["citation_hashes"])
                ),
                "lineage_fingerprints": sorted(
                    set(
                        query_agent_payload["context_bundle"][
                            "lineage_fingerprints"
                        ]
                    )
                    | set(source_recovery["lineage_fingerprints"])
                ),
                "source_recovery": source_recovery,
            }
            context_bundle.pop("bundle_fingerprint", None)
            context_bundle["bundle_fingerprint"] = sha256_json(context_bundle)
            query_agent_warnings = query_agent_payload.get("warnings", ())
            if not isinstance(query_agent_warnings, (list, tuple)) or any(
                not isinstance(warning, str) for warning in query_agent_warnings
            ):
                raise ContractValidationError(
                    "production query-agent warnings are invalid"
                )
            query_agent_payload = {
                **query_agent_payload,
                "warnings": list(
                    dict.fromkeys(
                        (*query_agent_warnings, *double_check.warnings)
                    )
                ),
                "context_bundle": context_bundle,
            }
        else:
            result_status = public_replan_status or result.status
        if placement is not None and result.status in {"error", "failed", "permission_denied"}:
            result_status = result.status  # An advisory replan cannot hide the original failure.
        evidence_result = MailEvidenceQueryResult(
            status="ok" if evidence else result_status,
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
                for provider in request_providers
                if provider.provider_fingerprint == page["provider_fingerprint"]
            )
            if len(selected_providers) != 1:
                raise ContractValidationError(
                    "production source occurrence provider binding is invalid"
                )
            provider = selected_providers[0]
            payload = {
                "status": public_replan_status or result.status,
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
            validate_projection(payload)
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
            "status": result_status,
            **({"presentation_truncated": True} if header_groups_truncated else {}),
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
        if placement is not None:
            # Preserve the existing envelope, source-recheck metadata, failures,
            # coverage and fingerprints. Only unproved initial answer content
            # is withheld; cited recheck groups retain their existing payload.
            citations = list(dict.fromkeys(item["citation_hash"] for item in evidence))
            answer_payload = {**payload["answer"], "text": "", "citation_count": len(citations)}
            answer_payload.pop("answer_hash", None)
            answer_payload["answer_hash"] = sha256_json(answer_payload)
            payload = {**payload, "answer": answer_payload, "citations": citations}
        validate_projection(payload)
        return payload

    retrieval_handler.authorized_capability_summary = authorized_capabilities
    retrieval_handler._issue56_allowed_relation_types = relation_types
    return retrieval_handler


def _attach_server_authorized_mail_capability_summary(
    handler: Callable[..., dict[str, Any]],
    *,
    session: Any,
    bundles: Sequence[Any],
    safe_binding: Mapping[str, Any],
    source_records: Any | None = None,
) -> None:
    """Expose one validated selector to the trusted UAT capability context.

    The mail handler is already built from server-owned source objects.  This
    seam only publishes the selector when the composition proves that exactly
    one owner-bound mail session is in scope; ambiguity leaves the handler
    without capability metadata so omission remains fail-closed.
    """

    raw_bundle_selector_ids = tuple(
        getattr(
            getattr(bundle, "mail_import_session", None),
            "mail_import_session_id",
            None,
        )
        for bundle in bundles
    )
    if any(
        not isinstance(value, str) or not value.strip()
        for value in raw_bundle_selector_ids
    ):
        raise ContractValidationError("mail selector binding is invalid")
    bundle_selector_ids = tuple(sorted(set(raw_bundle_selector_ids)))

    source_selector_ids: tuple[str, ...] = ()
    if source_records is not None:
        raw_source_selector_ids = getattr(
            source_records,
            "authorized_mail_import_session_ids",
            (),
        )
        if (
            not isinstance(raw_source_selector_ids, Sequence)
            or isinstance(raw_source_selector_ids, (str, bytes))
            or any(
                not isinstance(value, str) or not value.strip()
                for value in raw_source_selector_ids
            )
        ):
            raise ContractValidationError("mail source selector binding is invalid")
        source_selector_ids = tuple(sorted(set(raw_source_selector_ids)))
        if source_selector_ids and set(source_selector_ids) != set(bundle_selector_ids):
            raise ContractValidationError("mail source selector binding mismatch")

    selector_ids = source_selector_ids or bundle_selector_ids
    if len(selector_ids) != 1:
        # Never choose one selector from an ambiguous authorized scope.
        return

    import_sessions = tuple(
        getattr(bundle, "mail_import_session", None) for bundle in bundles
    )
    if not import_sessions or any(item is None for item in import_sessions):
        raise ContractValidationError("mail import session binding is unavailable")
    import_session = import_sessions[0]
    if any(
        getattr(item, "mail_import_session_id", None) != selector_ids[0]
        or getattr(item, "workspace_id", None) != getattr(import_session, "workspace_id", None)
        or getattr(item, "owner_user_id", None) != getattr(import_session, "owner_user_id", None)
        for item in import_sessions
    ):
        raise ContractValidationError("mail import session binding is inconsistent")

    if (
        getattr(session, "requester_user_id", None)
        != getattr(import_session, "owner_user_id", None)
        or getattr(session, "workspace_id", None)
        != getattr(import_session, "workspace_id", None)
    ):
        raise ContractValidationError("mail selector actor or workspace binding is invalid")
    authorized_source = getattr(session, "authorized_source", None)
    if (
        authorized_source is None
        or getattr(authorized_source, "source_kind", None)
        != AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
    ):
        raise ContractValidationError("mail authorized source binding is invalid")

    coverage = safe_binding.get("extraction_coverage", {})
    coverage_complete = (
        isinstance(coverage, Mapping)
        and coverage.get("source_completeness_certified") is True
        and not safe_binding.get("bounded_canary_candidate_count")
    )
    source_binding_fingerprint = getattr(
        session,
        "source_session_binding_fingerprint",
        None,
    )
    if not _is_sha256(source_binding_fingerprint):
        raise ContractValidationError("mail source capability binding is unavailable")
    capability_core = {
        "artifact_id": "formowl_server_authorized_mail_capability_v1",
        "source_families": ["mail"],
        "mail_selector_kind": "mail_import_session_id",
        "authorized_mail_import_session_ids": list(selector_ids),
        "selector_count": 1,
        "coverage_status": "complete" if coverage_complete else "incomplete",
    }
    handler.authorized_capability_summary = {
        **capability_core,
        "capability_fingerprint": sha256_json(
            {
                "source_session_binding_fingerprint": source_binding_fingerprint,
                **capability_core,
            }
        ),
    }


def build_issue56_production_semantic_handlers(
    *,
    query_agent_planner: AdaptiveQueryPlanner | None = None,
    ingestion_revision: Issue56IngestionRevision | None = None,
) -> tuple[
    Callable[..., dict[str, Any]],
    Callable[[dict[str, Any]], dict[str, Any]] | None,
]:
    """Build graph and mail handlers from one governed runtime source.

    The no-revision path loads the approved sealed source once, then derives
    both handlers from its permission-filtered runtime objects.  In
    particular, the mail handler receives the existing owner-produced
    ``query_bundle`` rather than reopening or bypassing the source.
    """

    if ingestion_revision is None:
        loaded = _load_approved_sealed_source(
            include_participant_authorization_observations=True
        )
        retrieval_handler = build_issue56_production_semantic_retrieval_handler(
            query_agent_planner=query_agent_planner,
            _loaded_source=loaded,
        )
        mail_evidence_handler = build_mail_evidence_query_handler(
            (loaded.query_bundle,),
        )
        _attach_server_authorized_mail_capability_summary(
            mail_evidence_handler,
            session=loaded.session,
            bundles=(loaded.query_bundle,),
            safe_binding=loaded.safe_binding,
        )
        return retrieval_handler, _closed_placement_mail_handler(mail_evidence_handler)

    if (
        ingestion_revision.session is not None
        and ingestion_revision.authorized_source is not None
        and ingestion_revision.source_records is not None
    ):
        _indexed_manifest, projection_failed = _reopen_indexed_projection(
            ingestion_revision
        )
        if projection_failed:
            return (
                _build_source_start_semantic_handler(
                    ingestion_revision, mail_tool=False,
                ),
                (
                    _build_source_start_semantic_handler(
                        ingestion_revision, mail_tool=True,
                    )
                    if ingestion_revision.authorized_source.authorizes_source_kind(
                        AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
                    ) and bool(getattr(
                        ingestion_revision.source_records,
                        "authorized_mail_import_session_ids",
                        (),
                    ))
                    else None
                ),
            )

    if (
        ingestion_revision.session is None
        and ingestion_revision.authorized_source is not None
    ):
        return (
            _build_source_start_semantic_handler(
                ingestion_revision, mail_tool=False,
            ),
            (
                _build_source_start_semantic_handler(
                    ingestion_revision, mail_tool=True,
                )
                if ingestion_revision.authorized_source.authorizes_source_kind(
                    AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND
                ) and bool(getattr(
                    ingestion_revision.source_records,
                    "authorized_mail_import_session_ids",
                    (),
                ))
                else None
            ),
        )

    retrieval_handler = build_issue56_production_semantic_retrieval_handler(
        query_agent_planner=query_agent_planner,
        ingestion_revision=ingestion_revision,
    )
    bundles = tuple(getattr(ingestion_revision, "bundles", ()))
    if bundles:
        mail_evidence_handler = build_mail_evidence_query_handler(bundles)
        _attach_server_authorized_mail_capability_summary(
            mail_evidence_handler,
            session=ingestion_revision.session,
            bundles=bundles,
            safe_binding=ingestion_revision.safe_binding,
            source_records=ingestion_revision.source_records,
        )
    else:
        authorized_source = getattr(
            ingestion_revision.session,
            "authorized_source",
            None,
        )
        if not getattr(
            ingestion_revision.source_records,
            "authorized_mail_import_session_ids",
            (),
        ):
            return retrieval_handler, None
        if (
            authorized_source is not None
            and authorized_source.source_kind == AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND
            and authorized_source.authorized_source_kinds
            == (AUTHORIZED_TEXT_OBSERVATION_SOURCE_KIND,)
        ):
            return retrieval_handler, None
        allowed_relation_types = getattr(
            retrieval_handler,
            "_issue56_allowed_relation_types",
            (),
        )
        if not isinstance(allowed_relation_types, tuple) or any(
            not isinstance(relation_type, str) or not relation_type
            for relation_type in allowed_relation_types
        ):
            allowed_relation_types = ()
        mail_evidence_handler = build_revision_owned_mail_evidence_query_handler(
            session=ingestion_revision.session,
            effective_graph_view=ingestion_revision.effective_graph_view,
            source_records=ingestion_revision.source_records,
            safe_binding=ingestion_revision.safe_binding,
            allowed_relation_types=allowed_relation_types,
        )
    return retrieval_handler, _closed_placement_mail_handler(mail_evidence_handler)


def _build_ingestion_source_occurrence_providers(
    session: Any,
    *,
    include_table_providers: bool = True,
) -> tuple[SourceOccurrenceProvider, ...]:
    """Use the complete staged job scope, not the legacy sealed subset manifests."""
    scope_fingerprint = authorized_source_occurrence_scope_fingerprint(
        requester_user_id=session.requester_user_id,
        workspace_id=session.workspace_id,
        source_scope_ids=session.authorized_source_scope_ids,
        authorized_observation_hashes=session.authorized_observation_hashes,
        source_session_binding_fingerprint=session.source_session_binding_fingerprint,
    )
    hashes = dict(session.authorized_observation_hashes)
    lineages = {item.source_observation_id: item for item in session.occurrence_lineages}
    profile = session.index._runtime_components.tokenizer_profile
    fields = {
        "participant.any.local_part": {},
        **{f"participant.{role}.local_part": {} for role in ("from", "sender", "to", "cc")},
        "message_occurrence.direct_source_identifier_v1": {},
    }
    unresolved = {field: set() for field in fields}
    occurrences = set()
    projections: dict[str, set[tuple[str, str, str, str]]] = {}
    registry = HeaderRegistry()
    for observation in session.authorized_observations:
        lineage = lineages[observation.observation_id]
        if not isinstance(lineage, MailMessageOccurrenceLineage):
            continue
        occurrence = lineage.occurrence_id
        occurrences.add(occurrence)
        citation, lineage_hash = hashes[observation.observation_id], lineage.lineage_fingerprint
        payload = observation.payload or {}
        if observation.observation_type == "email_message":
            display = [(key, payload.get(key)) for key in ("subject", "sender", "sent_at")]
            role, value = "from", payload.get("sender")
        elif observation.observation_type == "email_header":
            role, value = str(payload.get("header_name", "")).casefold(), payload.get("header_value")
            display = [(role, value)] if role in {"from", "sender", "to", "cc", "subject", "date"} else []
        else:
            role, value = "", None
            display = [("body_excerpt", observation.text)] if observation.observation_type == "email_body_segment" else []
        for field, raw in display:
            if isinstance(raw, str) and raw:
                safe = redact_public_raw_references(raw)[0][:400]
                projections.setdefault(occurrence, set()).add((field, safe, citation, lineage_hash))
        if role in {"from", "sender", "to", "cc"}:
            selected_fields = ("participant.any.local_part", f"participant.{role}.local_part")
            try:
                header = registry(role, value or "")
                if header.defects or not header.addresses:
                    raise ValueError("incomplete")
                addresses = tuple(normalize_verified_email(item.addr_spec) for item in header.addresses)
            except (AttributeError, TypeError, ValueError, ContractValidationError):
                for field in selected_fields:
                    unresolved[field].add(occurrence)
            else:
                for field in selected_fields:
                    for address in addresses:
                        fields[field].setdefault(occurrence, set()).add((
                            sha256_json(address.split("@", 1)[0]), sha256_json(address),
                            citation, lineage_hash,
                        ))
        for span in profile.analyze(observation.text or "").protected_identifiers:
            value_hash = sha256_json(span.exact_token)
            fields["message_occurrence.direct_source_identifier_v1"].setdefault(occurrence, set()).add(
                (value_hash, value_hash, citation, lineage_hash)
            )
    providers = []
    for field, bindings in (fields.items() if occurrences else ()):
        complete = {key: value for key, value in bindings.items() if key not in unresolved[field]}
        projected = {
            key: tuple(sorted(
                item for item in projections.get(key, ())
                if item[2:] in {binding[2:] for binding in value}
            ))
            for key, value in complete.items()
        }
        providers.append(SourceOccurrenceProvider(
            provider_id=("mail_message_occurrence_direct_source_identifier_provider_v1"
                         if field.startswith("message_occurrence.") else "mail_source_occurrence_provider_v1"),
            inventory_kind_alias="mail_observation", resource_kind="mail_message_occurrence",
            normalized_field=field, predicate="source_occurrence_involves",
            operator="case_insensitive_exact",
            requester_user_id=session.requester_user_id, workspace_id=session.workspace_id,
            source_scope_ids=session.authorized_source_scope_ids,
            authorized_scope_fingerprint=scope_fingerprint,
            occurrences=tuple(AuthorizedSourceOccurrence(
                item_hash=sha256_json(["mail_message_occurrence", key]),
                value_bindings=tuple(sorted(value)),
                projection_bindings=projected[key],
                structure_status="source_provided" if projected[key] else None,
            ) for key, value in sorted(complete.items())),
            unresolved_count=len(occurrences - set(complete)),
        ))
    if include_table_providers:
        for inline in (False, True):
            provider = _build_attachment_table_row_provider(
                session,
                authorized_scope_fingerprint=scope_fingerprint,
                inline_tables=inline,
            )
            if provider is not None:
                providers.append(provider)
    return tuple(providers)


@dataclass(frozen=True)
class _OnDemandIngestionProviderBatch:
    providers: tuple[SourceOccurrenceProvider, ...]
    observations_by_hash: Mapping[str, tuple[Observation, ...]]
    lineages_by_observation_id: Mapping[str, Any]
    authorized_reference_pairs: tuple[tuple[str, str], ...]


@contextmanager
def _native_planning_phase(metrics, stage):
    """Aggregate existing calls only; a completed call need not find a shard."""
    started = None
    if metrics is not None:
        try:
            metrics[f"native_{stage}_attempted"] += 1
            started = (time.monotonic(), time.thread_time())
        except Exception:
            metrics["native_phase_failed"] = 1
    completed = False
    try:
        yield
        completed = True
    finally:
        if started is not None:
            try:
                metrics[f"native_{stage}_wall_ms"] += round((time.monotonic() - started[0]) * 1000, 3)
                metrics[f"native_{stage}_cpu_ms"] += round((time.thread_time() - started[1]) * 1000, 3)
                metrics[f"native_{stage}_completed"] += int(completed)
            except Exception:
                metrics["native_phase_failed"] = 1


class _IngestionExactCellLookup:
    """Resolve only query-matched table rows from a sealed compact index."""

    def __init__(self, revision: Issue56IngestionRevision) -> None:
        profile = load_issue56_target_mail_tokenizer_profile()
        manifest = dict(revision.exact_lookup_manifest)
        if not manifest:
            raise ContractValidationError(
                "ingestion exact cell lookup is unavailable"
            )
        fingerprint = manifest.pop("manifest_fingerprint", None)
        columns = manifest.get("columns")
        shards = manifest.get("shards")
        counts = manifest.get("counts")
        if (
            revision.exact_lookup_directory is None
            or manifest.get("artifact_id")
            != "formowl_issue56_ingestion_exact_cell_lookup_v1"
            or manifest.get("schema_version") != 1
            or fingerprint != sha256_json(manifest)
            or manifest.get("source_authority_fingerprint")
            != revision.safe_binding.get("source_authority_fingerprint", getattr(revision.session, "source_authority_fingerprint", None))
            or manifest.get("tokenizer_profile_fingerprint")
            != profile.profile_fingerprint
            or manifest.get("job_count") != len(revision.job_authorities)
            or not isinstance(columns, list)
            or not isinstance(shards, list)
            or not isinstance(counts, dict)
        ):
            raise ContractValidationError(
                "ingestion exact cell lookup binding is invalid"
            )
        parsed_shards: dict[tuple[str, str], Mapping[str, Any]] = {}
        for item in shards:
            if (
                not isinstance(item, Mapping)
                or set(item)
                != {"kind", "shard", "record_count", "size_bytes", "sha256"}
                or item.get("kind") not in {"row", "value"}
                or not isinstance(item.get("shard"), str)
                or len(item["shard"]) != 2
                or any(character not in "0123456789abcdef" for character in item["shard"])
                or not isinstance(item.get("record_count"), int)
                or item["record_count"] < 1
                or not isinstance(item.get("size_bytes"), int)
                or item["size_bytes"] < 1
                or not _is_sha256(item.get("sha256"))
                or (item["kind"], item["shard"]) in parsed_shards
            ):
                raise ContractValidationError(
                    "ingestion exact cell lookup shard is invalid"
                )
            parsed_shards[(item["kind"], item["shard"])] = dict(item)
        parsed_columns: list[dict[str, Any]] = []
        normalized_columns: dict[str, set[str]] = {}
        for item in columns:
            if (
                not isinstance(item, Mapping)
                or set(item)
                != {
                    "field",
                    "column_hash",
                    "inline_table",
                    "structure_status",
                    "candidate_hashes",
                }
                or not isinstance(item.get("field"), str)
                or not item["field"]
                or not _is_sha256(item.get("column_hash"))
                or not isinstance(item.get("inline_table"), bool)
                or item.get("structure_status")
                not in {"source_provided", "candidate_only", "unavailable"}
                or not isinstance(item.get("candidate_hashes"), list)
                or not item["candidate_hashes"]
                or any(
                    not _is_sha256(value)
                    for value in item["candidate_hashes"]
                )
            ):
                raise ContractValidationError(
                    "ingestion exact cell lookup column is invalid"
                )
            parsed = dict(item)
            parsed_columns.append(parsed)
            normalized_field = normalize_source_occurrence_structured_surface(
                item["field"]
            )
            if normalized_field:
                normalized_columns.setdefault(normalized_field, set()).add(
                    item["column_hash"]
                )
        self._revision = revision
        self._tokenizer_profile = profile
        self._directory = revision.exact_lookup_directory
        self._manifest = MappingProxyType(
            {**manifest, "manifest_fingerprint": fingerprint}
        )
        self._shards = MappingProxyType(parsed_shards)
        self._columns = tuple(parsed_columns)
        self._normalized_columns = MappingProxyType(
            {
                key: frozenset(value)
                for key, value in normalized_columns.items()
            }
        )
        if revision.source_records is not None:
            reader = revision.source_records
            def _source_observation_or_none(key: str) -> Observation | None:
                try:
                    return reader.get_observation(key)
                except ContractValidationError:
                    return None

            def _source_lineage_or_none(key: str) -> Any | None:
                try:
                    return reader.lineage(key)
                except ContractValidationError:
                    return None

            self._base_observation_by_id = _KeyedIngestionLookup(
                _source_observation_or_none
            )
            self._base_lineage_by_id = _KeyedIngestionLookup(
                _source_lineage_or_none
            )
            self._attachment_parent_by_child_asset = _KeyedIngestionLookup(
                reader.attachment_parent_for_child_asset
            )
        else:
            self._base_observation_by_id = {
                observation.observation_id: observation
                for observation in revision.session.authorized_observations
            }
            self._base_lineage_by_id = {
                lineage.source_observation_id: lineage
                for lineage in revision.session.occurrence_lineages
            }
            self._attachment_parent_by_child_asset = {
                str((observation.payload or {}).get("child_asset_id")): observation
                for observation in revision.session.authorized_observations
                if observation.observation_type == "email_attachment_occurrence"
                and isinstance((observation.payload or {}).get("child_asset_id"), str)
            }

    @property
    def capability_fields(self) -> tuple[Mapping[str, Any], ...]:
        counts = self._manifest["counts"]
        return tuple(
            {
                "field": item["field"],
                "field_hash": item["column_hash"],
                "candidate_hashes": list(item["candidate_hashes"]),
                "structure_status": item["structure_status"],
                "authorized_occurrence_count": counts[
                    (
                        "inline_authorized_row"
                        if item["inline_table"]
                        else "attachment_authorized_row"
                    )
                ],
                "label_redacted": False,
            }
            for item in self._columns
        )

    def scan_source_rows(
        self, *, required_terms: Sequence[str], query_text: str,
        source_families: Sequence[str], mail_import_session_id: str | None,
        max_observations: int, deadline_monotonic: float,
        observation_callback: Callable[[Observation, str], bool],
        evidence_by_id: dict[str, dict[str, Any]],
        table_query: Mapping[str, Any] | None = None,
        native_group_callback: Callable[[tuple[Observation, ...]], None] | None = None,
        begin_family: Callable[[str], None] | None = None,
        _phase_metrics: dict[str, int | float] | None = None,
    ) -> RevisionOwnedMailSourceScan:
        """Use existing token/row shards; hydrate and admit only same-row evidence.

        Index records locate candidates, never prove values or field schema.
        Shard sealing, hydration, parent binding and projection share the caller's
        clock. No full-column value hash search or query-time rebuild is used.
        """
        revision = self._revision
        source = revision.authorized_source
        if source is None:
            raise ContractValidationError("source table authority is unavailable")
        scanned = 0
        read_start = 0
        context_bytes = 0

        class Stopped(Exception):
            pass

        def check() -> None:
            if time.monotonic() >= deadline_monotonic:
                raise Stopped("deadline")

        def load(job_index: int, observation_id: str, observation_hash: str) -> Observation:
            nonlocal scanned
            check()
            if scanned - read_start >= max_observations:
                raise Stopped("observation_limit")
            if (type(job_index) is not int or not 0 <= job_index < len(revision.job_authorities)
                    or not isinstance(observation_id, str) or not _is_sha256(observation_hash)):
                raise ContractValidationError("source table reference is invalid")
            scanned += 1
            authority = revision.job_authorities[job_index]
            item = authority.load_indexed_observation(
                observation_id, expected_observation_hash=observation_hash,
                expected_job_fingerprint=authority.job_fingerprint,
            )
            check()
            if not authorized_permission_scope_matches(
                item.permission_scope, authorized_source=source,
                source_kind=AUTHORIZED_MAIL_OBSERVATION_SOURCE_KIND,
            ):
                raise ContractValidationError("source table permission is denied")
            return item

        def hydrate() -> None:
            nonlocal context_bytes
            def matched_rows():
                # Seal one shard, emit its verified rows, then proceed. A later
                # deadline cannot discard already admitted same-row evidence.
                for shard in sorted({key[7:9] for key in row_keys}):
                    local_keys = {key for key in row_keys if key[7:9] == shard}
                    with _native_planning_phase(_phase_metrics, "rows"):
                        records = self._read_matching_shard_records(
                            "row", shard, matching_keys=local_keys, check=check,
                            maximum_matching_records=max_observations,
                        )
                    if records is None:
                        raise Stopped("observation_limit")
                    by_row: dict[str, list[Any]] = {key: [] for key in local_keys}
                    for record in records:
                        by_row[record[1]].append(record)
                    for key in sorted(local_keys):
                        yield key, row_keys[key], by_row[key]

            for row_key, inline, selected_records in matched_rows():
                check()
                subset = []
                job_indexes = set()
                for record in selected_records:
                    if record[-1] != inline:
                        raise ContractValidationError("source table family binding mismatch")
                    item = load(record[2], record[3], record[4])
                    if (sha256_json(_table_row_key(item)) != row_key
                            or item.observation_type != ("table_row" if record[0] == "row" else "table_cell")):
                        raise ContractValidationError("source table row binding mismatch")
                    subset.append(item)
                    job_indexes.add(record[2])
                rows = [item for item in subset if item.observation_type == "table_row"]
                cells = sorted((item for item in subset if item.observation_type == "table_cell"),
                               key=lambda item: item.location.get("cell_index", 0))
                if len(rows) != 1 or not cells or len(job_indexes) != 1:
                    raise ContractValidationError("source table row reference is incomplete")
                row = rows[0]
                if table_query is not None:
                    matches = all(any(
                        normalize_source_occurrence_structured_surface((cell.payload or {}).get("table_structure", {}).get("column_name") or "")
                        == normalize_source_occurrence_structured_surface(predicate["field"])
                        and normalize_source_occurrence_structured_surface(cell.text or "")
                        == normalize_source_occurrence_structured_surface(predicate["value"])
                        for cell in cells) for predicate in table_query["filters"])
                    if matches and terms:
                        normalized_cells = [
                            unicodedata.normalize("NFKC", cell.text or "").casefold()
                            for cell in cells
                        ]
                        matches = all(
                            any(
                                re.search(rf"(?<!\w){re.escape(term)}(?!\w)", cell_text)
                                if term.isdecimal() else term in cell_text
                                for cell_text in normalized_cells
                            )
                            for term in terms
                        )
                else:
                    def term_matches(term: str) -> bool:
                        bindings = typed_term_bindings.get(term)
                        if bindings:
                            binding_values = {
                                (
                                    normalize_source_occurrence_structured_surface(field),
                                    normalize_source_occurrence_structured_surface(value),
                                )
                                for field, value in bindings
                            }
                            return any(
                                (
                                    normalize_source_occurrence_structured_surface(
                                        (cell.payload or {}).get("table_structure", {}).get("column_name") or ""
                                    ),
                                    normalize_source_occurrence_structured_surface(cell.text or ""),
                                ) in binding_values
                                for cell in cells
                            )
                        normalized_term = unicodedata.normalize("NFKC", term).casefold()
                        return any(
                            normalized_term in unicodedata.normalize("NFKC", cell.text or "").casefold()
                            for cell in cells
                        )

                    matches = all(term_matches(term) for term in terms)
                if not matches:
                    continue
                job_index = next(iter(job_indexes))
                nested = (row.payload or {}).get("lineage", {})
                parent_id = nested.get("parent_message_observation_id" if inline else "parent_attachment_observation_id")
                parent = None
                reader = revision.source_records
                runtime_store = reader.runtime_store
                helper = None
                if parent_id is not None and callable(getattr(runtime_store, "get_helper", None)):
                    helper = runtime_store.get_helper(parent_id)
                elif not inline and callable(getattr(runtime_store, "helper_for_attachment_asset", None)):
                    helper = runtime_store.helper_for_attachment_asset(row.asset_id)
                check()
                if helper is not None:
                    reader._authority_for_helper(helper)
                    if helper["reference"]["job_index"] != job_index:
                        raise ContractValidationError("source table parent job mismatch")
                    parent = load(job_index, helper["observation_id"], helper["observation_hash"])
                if parent is None:
                    raise Stopped("source_parent_binding_unresolved")
                if ((inline and parent.observation_type != "email_message") or (
                        not inline and (parent.observation_type != "email_attachment_occurrence"
                                        or (parent.payload or {}).get("child_asset_id") != row.asset_id))):
                    raise ContractValidationError("source table parent binding mismatch")
                selector = _authorized_mail_selector_for_asset(revision.job_authorities[job_index].asset)
                if mail_import_session_id is not None and selector != mail_import_session_id:
                    continue
                parent_lineage = source_occurrence_lineage_from_observation(parent, authorized_source=source)
                if inline and not isinstance((parent.payload or {}).get("message_fingerprint"), str):
                    raise Stopped("source_parent_binding_unresolved")
                lineages = normalized_authorized_observation_lineages(
                    (parent, *subset), authorized_source=source, occurrence_lineages=(parent_lineage,),
                )
                lineage_by_id = {item.source_observation_id: item for item in lineages}
                row_hash = sha256_json(row.to_dict())
                # Stage one genuine source row, including every verified member.
                # A callback/evidence/byte/deadline boundary must never detach a
                # value from its later anchor or from its native row citation.
                members = []
                content_redacted = False
                for cell in cells:
                    check()
                    if cell.permission_scope != row.permission_scope or cell.extractor_run_id != row.extractor_run_id:
                        raise ContractValidationError("source table cell scope mismatch")
                    structure = (cell.payload or {}).get("table_structure", {})
                    row_structure = (row.payload or {}).get("table_structure", {})
                    structure_status = _effective_cell_structure_status(self._revision, cell, row_structure)
                    field = structure.get("column_name") or f"column_{cell.location.get('cell_index')}"
                    value, redacted = redact_public_raw_references(cell.text or "")
                    safe_field, field_redacted = redact_public_raw_references(field)
                    member = {
                        "citation_hash": sha256_json(cell.to_dict()),
                        "occurrence_lineage_fingerprint": lineage_by_id[cell.observation_id].lineage_fingerprint,
                        "source_observation_id": cell.observation_id,
                        "coordinates": {key: cell.location[key] for key in (
                            "sheet_name", "table_index", "row_index", "cell_index", "cell_ref",
                        ) if key in cell.location},
                        "field": safe_field[:120], "value": value[:400],
                        "field_truncated": len(safe_field) > 120,
                        "value_truncated": len(value) > 400,
                        "structure_status": structure_status,
                        "source_proven_field_schema": (
                            (
                                (structure_status == "source_provided"
                                 and row_structure.get("structure_status") == "source_provided")
                                or structure_status == "reviewed_header"
                            )
                            and not redacted and not field_redacted and len(field) <= 120 and len(value) <= 400
                        ),
                    }
                    native = (cell.payload or {}).get("native", {})
                    if isinstance(native, Mapping):
                        native_display = native.get("display_value")
                        native_display_status = native.get("display_value_status")
                        if (
                            native_display_status != "available"
                            and native.get("date_value_status") in {
                                "normalized_excel_serial", "phantom_1900_leap_day",
                            }
                        ):
                            native_display = native.get("date_value_iso")
                        if isinstance(native_display, str) and native_display.strip():
                            safe_display = redact_public_raw_references(native_display)[0]
                            if safe_display and safe_display != value:
                                member["display_value"] = safe_display[:400]
                                member["display_value_status"] = (
                                    "source_display" if native_display_status == "available"
                                    else "derived_date_value_iso"
                                )
                    members.append(member)
                    content_redacted |= bool(redacted or field_redacted)
                item = {
                    "snippet": "Verified same-row cells; field schema status is given per member.",
                    "citation_hash": row_hash,
                    "occurrence_lineage_fingerprint": lineage_by_id[row.observation_id].lineage_fingerprint,
                    "source_scope_fingerprint": sha256_json(row.permission_scope["scope_id"]),
                    "content_redacted": content_redacted,
                    "table_row": {
                        "source_observation_id": row.observation_id,
                        "coordinates": {key: row.location[key] for key in (
                            "sheet_name", "table_index", "row_index",
                        ) if key in row.location},
                        "cells": members,
                    },
                    "revision_binding": {
                        "source_authority_fingerprint": revision.safe_binding["source_authority_fingerprint"],
                        "source_session_binding_fingerprint": revision.safe_binding["source_session_binding_fingerprint"],
                    },
                }
                if selector is not None:
                    item["mail_import_session_id"] = selector
                if inline:
                    item.update({
                        "source_type": "mail_inline_table_row",
                        "source_observation_id": row.observation_id,
                        "source_observation_hash": row_hash,
                        "email_message_id": stable_resource_contract_id(
                            "emailmsg", "EmailMessage", {"message_fingerprint": parent.payload["message_fingerprint"]},
                        ),
                        "message_occurrence_id": parent_lineage.message_occurrence_id,
                    })
                    # The existing mail presentation keeps snippet/citation
                    # fields, not table metadata. Carry the same whole group in
                    # its snippet so compaction cannot discard the row's cells.
                    item["snippet"] = json.dumps({
                        "citation_hash": row_hash,
                        "occurrence_lineage_fingerprint": item["occurrence_lineage_fingerprint"],
                        "table_row": item["table_row"],
                    }, ensure_ascii=False, separators=(",", ":"))
                size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
                check()
                if context_bytes + size > 16 * 1024:
                    raise Stopped("context_limit")
                context_bytes += size
                evidence_by_id[row.observation_id] = item
                if native_group_callback is not None:
                    native_group_callback((parent, *subset))
                if not observation_callback(row, row.permission_scope["scope_id"]):
                    raise Stopped("callback")

        try:
            check()
            with _native_planning_phase(_phase_metrics, "terms"):
                terms = tuple(required_terms) or (() if table_query is not None else tuple(
                    span.exact_token for span in self._tokenizer_profile.analyze(query_text).protected_identifiers
                ))
                if not terms and table_query is None:
                    return RevisionOwnedMailSourceScan((), 0, False, "source_table_anchor_unresolved")
                hashes = set()
                typed_hashes = set()
                typed_term_bindings: dict[str, tuple[tuple[str, str], ...]] = {}
                for term in terms:
                    check()
                    normalized_term = unicodedata.normalize("NFKC", term).casefold()
                    if table_query is None:
                        # Candidate-only attachment tables can still contain a
                        # native numeric value for a typed identifier (for
                        # example PO470002002 -> 470002002). Use the sealed
                        # candidate schema to locate that row; hydration keeps
                        # candidate_only status and cannot promote it to exact.
                        schema_fields = tuple(item["field"] for item in self._columns)
                        if re.match(r"po[0-9]+$", normalized_term):
                            po_fields = tuple(
                                field for field in schema_fields
                                if re.search(r"(?<![a-z0-9])po(?![a-z0-9])", field.casefold())
                                and re.search(r"(?<![a-z0-9])(no|number)(?![a-z0-9])", field.casefold())
                            )
                            if po_fields:
                                header_po_fields = tuple(
                                    field for field in po_fields
                                    if normalize_source_occurrence_structured_surface(field)
                                    == "header po no."
                                )
                                schema_fields = header_po_fields or po_fields
                        elif re.fullmatch(r"[0-9]+\.[a-z0-9][a-z0-9._-]*", normalized_term):
                            schema_fields = _part_identifier_schema_fields(schema_fields)
                        bindings = bind_typed_identifier_to_source_schema(
                            term, schema_fields,
                        )
                        if not bindings and re.fullmatch(
                                r"[0-9]+\.[a-z0-9][a-z0-9._-]*", normalized_term):
                            bindings = tuple((field, term) for field in schema_fields)
                        if bindings:
                            typed_term_bindings[term] = bindings
                            for field, value in bindings:
                                normalized_field = normalize_source_occurrence_structured_surface(field)
                                attachment_column_hashes = tuple(dict.fromkeys(
                                    item["column_hash"] for item in self._columns
                                    if normalize_source_occurrence_structured_surface(item["field"])
                                    == normalized_field and not item["inline_table"]
                                ))
                            if source_families == ("attachment_table",):
                                column_hashes = attachment_column_hashes
                            elif source_families == ("mail",):
                                inline_column_hashes = tuple(dict.fromkeys(
                                    item["column_hash"] for item in self._columns
                                    if normalize_source_occurrence_structured_surface(item["field"])
                                    == normalized_field and item["inline_table"]
                                ))
                                column_hashes = inline_column_hashes or self._normalized_columns.get(
                                    normalized_field, ()
                                )
                            else:
                                column_hashes = attachment_column_hashes or self._normalized_columns.get(
                                    normalized_field, ()
                                )
                            for column_hash in column_hashes:
                                value_hash = source_occurrence_exact_cell_value_hash(column_hash, value)
                                typed_hashes.add(value_hash)
                                hashes.add(value_hash)
                    if term not in typed_term_bindings:
                        hashes.update(
                            sha256_json(token)
                            for token in self._tokenizer_profile.analyze(term).tokens
                        )
                # If the attachment query has two independent native schema
                # bindings (the part identifier and its PO), those bindings
                # already define the same-row anchor. Do not spend the
                # bounded attachment slice on auxiliary protected tokens
                # from the surrounding Chinese request; mail text keeps the
                # ordinary token path in its separate engine.
                if (
                    table_query is None
                    and source_families == ("attachment_table",)
                    and len(typed_term_bindings) >= 2
                ):
                    terms = tuple(sorted(typed_term_bindings))
                    hashes = typed_hashes
                if table_query is not None:
                    # Resolve literal source-cell predicates through the existing
                    # sealed value shards, independently of tokenizer protection.
                    for predicate in table_query["filters"]:
                        column_hashes = self._normalized_columns.get(
                            normalize_source_occurrence_structured_surface(predicate["field"]), (),
                        )
                        hashes.update(source_occurrence_exact_cell_value_hash(column, predicate["value"])
                                      for column in column_hashes)
            if not hashes:
                return RevisionOwnedMailSourceScan((), 0, False, "source_table_anchor_unresolved")
            row_keys: dict[str, bool] = {}
            prefilter_count = 0
            for shard in sorted({key[7:9] for key in hashes}):
                with _native_planning_phase(_phase_metrics, "values"):
                    records = self._read_matching_shard_records(
                        "value", shard, matching_keys=hashes, check=check,
                        maximum_matching_records=max_observations,
                    )
                if records is None:
                    raise Stopped("observation_limit")
                prefilter_count = max(prefilter_count, len(records))
                for _, row_key, inline in records:
                    family = "mail" if inline else "attachment_table"
                    if family in source_families:
                        if row_key in row_keys and row_keys[row_key] != inline:
                            raise ContractValidationError("source table family is ambiguous")
                        row_keys[row_key] = inline
                        if len(row_keys) > max_observations:
                            raise Stopped("observation_limit")
            if begin_family is None:
                hydrate()
            else:
                # Discovery is complete and sealed before any family turn.
                # Full pre-filter multiplicity still governs each local cap.
                engine_limit, engine_deadline = max_observations, deadline_monotonic
                discovered = row_keys
                reason = "source_table_shortlist"
                for index, family in enumerate(source_families):
                    left = len(source_families) - index
                    read_start = scanned
                    max_observations = (engine_limit - scanned) // left
                    now = time.monotonic()
                    deadline_monotonic = now + max(0, engine_deadline - now) / left
                    row_keys = {key: inline for key, inline in discovered.items()
                                if ("mail" if inline else "attachment_table") == family}
                    context_bytes = 0
                    try:
                        check()
                        begin_family(family)
                        if (max_observations <= 0 or prefilter_count > max_observations
                                or len(row_keys) > max_observations):
                            raise Stopped("observation_limit")
                        hydrate()
                    except Stopped as exc:
                        reason = str(exc)
                        if reason in {"callback", "context_limit"} or time.monotonic() >= engine_deadline:
                            break
                return RevisionOwnedMailSourceScan((), scanned, False, reason)
            # Token shortlists and native XML values never certify completeness.
            return RevisionOwnedMailSourceScan((), scanned, False, "source_table_shortlist")
        except Stopped as exc:
            return RevisionOwnedMailSourceScan((), scanned, False, str(exc))

    @property
    def capability_providers(self) -> tuple[Mapping[str, Any], ...]:
        counts = self._manifest["counts"]
        result = []
        for inline in (False, True):
            authorized = counts[
                "inline_authorized_row"
                if inline
                else "attachment_authorized_row"
            ]
            if authorized == 0:
                continue
            result.append(
                {
                    "provider_fingerprint": sha256_json(
                        [
                            "on_demand_ingestion_table_provider_v1",
                            self._manifest["manifest_fingerprint"],
                            inline,
                        ]
                    ),
                    "source_family": "mail" if inline else "attachment_table",
                    "filter_slot_policy": "combined_present_intersection_v1",
                    "resource_kind": (
                        "mail_inline_table_row_occurrence"
                        if inline
                        else "attachment_table_row_occurrence"
                    ),
                    "normalized_field": "table.row.cell_value",
                    "source_provided_occurrence_count": authorized
                    - counts[
                        "inline_unresolved_row"
                        if inline
                        else "attachment_unresolved_row"
                    ],
                    "candidate_only_occurrence_count": counts[
                        "candidate_only_row"
                    ],
                }
            )
        return tuple(result)

    def providers_for_request(
        self,
        *,
        query_text: str,
        table_query: Mapping[str, Any] | None,
        authorized_scope_fingerprint: str,
    ) -> _OnDemandIngestionProviderBatch:
        analysis = (
            self._revision.session.index._runtime_components.tokenizer_profile
            .analyze(query_text)
        )
        candidate_hashes = {
            sha256_json(span.exact_token)
            for span in analysis.protected_identifiers
            if span.exact_token
        }
        if table_query is None and not candidate_hashes:
            return _OnDemandIngestionProviderBatch(
                providers=(),
                observations_by_hash=MappingProxyType({}),
                lineages_by_observation_id=MappingProxyType({}),
                authorized_reference_pairs=(),
            )
        if table_query is not None:
            raw_filters = table_query.get("filters")
            if not isinstance(raw_filters, list):
                raise ContractValidationError(
                    "ingestion exact cell table query is invalid"
                )
            for raw_filter in raw_filters:
                if not isinstance(raw_filter, Mapping):
                    raise ContractValidationError(
                        "ingestion exact cell table query is invalid"
                    )
                field = raw_filter.get("field")
                value = raw_filter.get("value")
                if not isinstance(field, str) or not isinstance(value, str):
                    raise ContractValidationError(
                        "ingestion exact cell table query is invalid"
                    )
                normalized_field = normalize_source_occurrence_structured_surface(
                    field
                )
                column_hashes = self._normalized_columns.get(
                    normalized_field,
                    frozenset(),
                )
                safe_value = redact_public_raw_references(value)[0][:400]
                candidate_hashes.update(
                    source_occurrence_exact_cell_value_hash(
                        column_hash,
                        safe_value,
                    )
                    for column_hash in column_hashes
                )
        row_keys_by_family: dict[bool, set[str]] = {
            False: set(),
            True: set(),
        }
        value_hashes_by_shard: dict[str, set[str]] = {}
        for candidate_hash in candidate_hashes:
            value_hashes_by_shard.setdefault(candidate_hash[7:9], set()).add(
                candidate_hash
            )
        for shard, matching_keys in sorted(value_hashes_by_shard.items()):
            for record in self._read_matching_shard_records(
                "value",
                shard,
                matching_keys=matching_keys,
            ):
                if (
                    not isinstance(record, list)
                    or len(record) != 3
                    or record[0] not in matching_keys
                    or not _is_sha256(record[1])
                    or not isinstance(record[2], bool)
                ):
                    continue
                row_keys_by_family[record[2]].add(record[1])
        row_keys = set().union(*row_keys_by_family.values())
        row_records_by_key: dict[str, list[list[Any]]] = {
            key: [] for key in row_keys
        }
        for shard in sorted({key[7:9] for key in row_keys}):
            for record in self._read_matching_shard_records(
                "row",
                shard,
                matching_keys=row_keys,
            ):
                if (
                    isinstance(record, list)
                    and len(record) in {6, 7}
                    and record[0] in {"row", "cell"}
                    and record[1] in row_records_by_key
                ):
                    row_records_by_key[record[1]].append(record)
        loaded_observations_by_family: dict[bool, dict[str, Observation]] = {
            False: {},
            True: {},
        }
        for inline, row_keys in row_keys_by_family.items():
            pending_keys = list(row_keys)
            queued_keys = set(row_keys)
            loaded_keys: set[str] = set()
            header_permissions: dict[str, Mapping[str, Any]] = {}
            while pending_keys:
                key = pending_keys.pop()
                records = row_records_by_key.get(key)
                if records is None:
                    records = self._read_matching_shard_records(
                        "row", key[7:9], matching_keys={key}
                    )
                selected_records = [
                    record for record in records
                    if record[1] == key and record[-1] is inline
                ]
                if not any(record[0] == "row" for record in selected_records):
                    raise ContractValidationError(
                        "ingestion exact cell row reference is incomplete"
                    )
                loaded_rows = []
                for record in selected_records:
                    job_index, observation_id, observation_hash = (
                        record[2], record[3], record[4]
                    )
                    if (
                        not isinstance(job_index, int)
                        or isinstance(job_index, bool)
                        or not 0 <= job_index < len(self._revision.job_authorities)
                        or not isinstance(observation_id, str)
                        or not _is_sha256(observation_hash)
                    ):
                        raise ContractValidationError(
                            "ingestion exact cell reference is invalid"
                        )
                    authority = self._revision.job_authorities[job_index]
                    observation = authority.load_indexed_observation(
                        observation_id,
                        expected_observation_hash=observation_hash,
                        expected_job_fingerprint=authority.job_fingerprint,
                    )
                    expected_type = (
                        "table_row" if record[0] == "row" else "table_cell"
                    )
                    if (
                        sha256_json(_table_row_key(observation)) != key
                        or observation.observation_type != expected_type
                        or (
                            key in header_permissions
                            and observation.permission_scope != header_permissions[key]
                        )
                    ):
                        raise ContractValidationError(
                            "ingestion exact cell row binding is invalid"
                        )
                    existing = loaded_observations_by_family[inline].get(
                        observation_id
                    )
                    if existing is not None and existing != observation:
                        raise ContractValidationError(
                            "ingestion exact cell reference is ambiguous"
                        )
                    loaded_observations_by_family[inline][
                        observation_id
                    ] = observation
                    if observation.observation_type == "table_row":
                        loaded_rows.append(observation)
                loaded_keys.add(key)

                for row in loaded_rows:
                    structure = (row.payload or {}).get("table_structure")
                    if (
                        not isinstance(structure, Mapping)
                        or structure.get("structure_status") != "candidate_only"
                    ):
                        continue
                    header_row_index = structure.get("header_row_index")
                    if (
                        not isinstance(header_row_index, int)
                        or isinstance(header_row_index, bool)
                        or header_row_index < 0
                    ):
                        raise ContractValidationError(
                            "ingestion exact cell candidate header locator is invalid"
                        )
                    header_key = sha256_json(
                        (*_table_row_key(row)[:-1], header_row_index)
                    )
                    prior_permission = header_permissions.get(header_key)
                    if (
                        prior_permission is not None
                        and prior_permission != row.permission_scope
                    ):
                        raise ContractValidationError(
                            "ingestion exact cell candidate header scope mismatch"
                        )
                    header_permissions[header_key] = row.permission_scope
                    if header_key in loaded_keys:
                        if any(
                            sha256_json(_table_row_key(item)) == header_key
                            and item.permission_scope != row.permission_scope
                            for item in loaded_observations_by_family[inline].values()
                        ):
                            raise ContractValidationError(
                                "ingestion exact cell candidate header scope mismatch"
                            )
                    elif header_key not in queued_keys:
                        queued_keys.add(header_key)
                        pending_keys.append(header_key)
        providers: list[SourceOccurrenceProvider] = []
        observations_by_hash: dict[str, list[Observation]] = {}
        lineages_by_observation_id: dict[str, Any] = {}
        reference_pairs: set[tuple[str, str]] = set()
        counts = self._manifest["counts"]
        for inline, loaded_by_id in loaded_observations_by_family.items():
            if not loaded_by_id:
                continue
            rows = tuple(
                observation
                for observation in loaded_by_id.values()
                if observation.observation_type == "table_row"
            )
            parents: dict[str, Observation] = {}
            for row in rows:
                if inline:
                    parent_id = (
                        (row.payload or {})
                        .get("lineage", {})
                        .get("parent_message_observation_id")
                    )
                    parent = self._base_observation_by_id.get(parent_id)
                else:
                    parent = self._attachment_parent_by_child_asset.get(
                        row.asset_id or ""
                    )
                if parent is None:
                    raise ContractValidationError(
                        "ingestion exact cell parent binding is unavailable"
                    )
                parents[parent.observation_id] = parent
            subset = tuple(
                sorted(
                    (*parents.values(), *loaded_by_id.values()),
                    key=lambda item: item.observation_id,
                )
            )
            parent_lineages = tuple(
                self._base_lineage_by_id[parent_id]
                for parent_id in sorted(parents)
            )
            lineages = normalized_authorized_observation_lineages(
                subset,
                authorized_source=self._revision.session.authorized_source,
                occurrence_lineages=parent_lineages,
            )
            hashes = tuple(
                sorted(
                    (
                        observation.observation_id,
                        sha256_json(observation.to_dict()),
                    )
                    for observation in subset
                )
            )
            subset_session = replace(
                self._revision.session,
                authorized_observations=subset,
                authorized_observation_hashes=hashes,
                occurrence_lineages=lineages,
            )
            provider = _build_attachment_table_row_provider(
                subset_session,
                authorized_scope_fingerprint=authorized_scope_fingerprint,
                inline_tables=inline,
            )
            if provider is None:
                continue
            authorized_count = counts[
                "inline_authorized_row"
                if inline
                else "attachment_authorized_row"
            ]
            unresolved_count = counts[
                "inline_unresolved_row"
                if inline
                else "attachment_unresolved_row"
            ]
            provider = replace(
                provider,
                unresolved_count=unresolved_count,
                authorized_occurrence_scope_count=authorized_count,
                extractable_occurrence_scope_count=(
                    authorized_count - unresolved_count
                ),
                source_asset_reason_counts=(),
            )
            providers.append(provider)
            for observation_id, observation_hash in hashes:
                observation = next(
                    item
                    for item in subset
                    if item.observation_id == observation_id
                )
                observations_by_hash.setdefault(
                    observation_hash,
                    [],
                ).append(observation)
            for lineage in lineages:
                lineages_by_observation_id[
                    lineage.source_observation_id
                ] = lineage
                observation_hash = dict(hashes)[
                    lineage.source_observation_id
                ]
                reference_pairs.add(
                    (observation_hash, lineage.lineage_fingerprint)
                )
        return _OnDemandIngestionProviderBatch(
            providers=tuple(providers),
            observations_by_hash=MappingProxyType(
                {
                    key: tuple(value)
                    for key, value in observations_by_hash.items()
                }
            ),
            lineages_by_observation_id=MappingProxyType(
                lineages_by_observation_id
            ),
            authorized_reference_pairs=tuple(sorted(reference_pairs)),
        )

    def _read_matching_shard_records(
        self,
        kind: str,
        shard: str,
        *,
        matching_keys: set[str],
        check: Callable[[], None] | None = None,
        maximum_matching_records: int | None = None,
    ) -> tuple[Any, ...] | None:
        """Seal every byte, decoding only the bounded keyed shortlist.

        The preparation pins the offline writer's JSONL bytes. A canonical key
        prefix is only a cheap prefilter, never evidence: selected records still
        require JSON/schema validation, and nothing is returned before the
        complete byte/count seal passes. Noncanonical prefixes take the parser
        path rather than silently dropping a possible escaped JSON key.
        """
        if not matching_keys:
            return ()
        binding = self._shards.get((kind, shard))
        if binding is None:
            return ()
        path = self._directory / (
            "values" if kind == "value" else "rows"
        ) / f"{shard}.jsonl"
        digest = hashlib.sha256()
        size = 0
        record_count = 0
        records: list[Any] = []
        matching_bytes = {key.encode("ascii") for key in matching_keys}
        prefix = re.compile(
            rb'^\s*\[\s*' + (rb'"(?:row|cell)"\s*,\s*' if kind == "row" else b"")
            + rb'"(sha256:[0-9a-f]{64})"'
        )
        overflow = False
        checked_size = 0
        if check is not None:
            check()
        try:
            if path.is_symlink():
                raise ContractValidationError("ingestion exact cell lookup shard is unavailable")
            with path.open("rb") as stream:
                # Native index records hold IDs/hashes, not source content.
                # Bound a corrupt unterminated line as well as retained records.
                def sealed_lines():
                    pending = b""
                    # Batch I/O and hashing, not validation or deadline polling.
                    # The partial line plus new bytes never exceeds the old
                    # bounded readline size; split only on LF, like readline.
                    while chunk := stream.read(16 * 1024 + 1 - len(pending)):
                        digest.update(chunk)
                        block = pending + chunk
                        if b"\r" in block:
                            # bytes.splitlines also splits bare CR; readline
                            # does not. Keep the exact LF-only fallback.
                            lines = block.split(b"\n")
                            pending = lines.pop()
                            for item in lines:
                                yield item + b"\n"
                        else:
                            lines = block.splitlines(keepends=True)
                            pending = b"" if block.endswith(b"\n") else lines.pop()
                            yield from lines
                        if len(pending) > 16 * 1024:
                            raise ContractValidationError("ingestion exact cell lookup record is oversized")
                    if pending:
                        yield pending

                for line in sealed_lines():
                    if len(line) > 16 * 1024:
                        raise ContractValidationError("ingestion exact cell lookup record is oversized")
                    if check is not None and (record_count % 128 == 0 or size - checked_size >= 64 * 1024):
                        check()
                        checked_size = size
                    size += len(line)
                    record_count += 1
                    if size > binding["size_bytes"]:
                        raise ContractValidationError("ingestion exact cell lookup shard seal mismatch")
                    if record_count > binding["record_count"]:
                        raise ContractValidationError("ingestion exact cell lookup shard count mismatch")
                    candidate = prefix.match(line)
                    if candidate is not None and candidate[1] not in matching_bytes:
                        continue
                    if check is not None:
                        check()
                    try:
                        record = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ContractValidationError(
                            "ingestion exact cell lookup shard is invalid"
                        ) from exc
                    if kind == "value":
                        if (
                            not isinstance(record, list)
                            or len(record) != 3
                            or not _is_sha256(record[0])
                            or not _is_sha256(record[1])
                            or not isinstance(record[2], bool)
                        ):
                            raise ContractValidationError(
                                "ingestion exact cell lookup value record is invalid"
                            )
                        record_key = record[0]
                    else:
                        if (
                            not isinstance(record, list)
                            or len(record) not in {6, 7}
                            or record[0] not in {"row", "cell"}
                            or not _is_sha256(record[1])
                            or not isinstance(record[-1], bool)
                        ):
                            raise ContractValidationError(
                                "ingestion exact cell lookup row record is invalid"
                            )
                        record_key = record[1]
                    if record_key in matching_keys:
                        if maximum_matching_records is not None and len(records) >= maximum_matching_records:
                            overflow = True
                        else:
                            records.append(record)
        except OSError as exc:
            raise ContractValidationError(
                "ingestion exact cell lookup shard is unavailable"
            ) from exc
        if (
            size != binding["size_bytes"]
            or "sha256:" + digest.hexdigest() != binding["sha256"]
        ):
            raise ContractValidationError(
                "ingestion exact cell lookup shard seal mismatch"
            )
        if record_count != binding["record_count"]:
            raise ContractValidationError(
                "ingestion exact cell lookup shard count mismatch"
            )
        if check is not None:
            check()
        return None if overflow else tuple(records)

    def _read_shard_records(
        self,
        kind: str,
        shard: str,
        *,
        cache: dict[tuple[str, str], tuple[Any, ...]],
    ) -> tuple[Any, ...]:
        key = (kind, shard)
        if key in cache:
            return cache[key]
        binding = self._shards.get(key)
        if binding is None:
            cache[key] = ()
            return ()
        path = self._directory / (
            "values" if kind == "value" else "rows"
        ) / f"{shard}.jsonl"
        try:
            payload = path.read_bytes()
        except OSError as exc:
            raise ContractValidationError(
                "ingestion exact cell lookup shard is unavailable"
            ) from exc
        if (
            len(payload) != binding["size_bytes"]
            or "sha256:" + hashlib.sha256(payload).hexdigest()
            != binding["sha256"]
        ):
            raise ContractValidationError(
                "ingestion exact cell lookup shard seal mismatch"
            )
        try:
            records = tuple(
                json.loads(line)
                for line in payload.decode("utf-8").splitlines()
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractValidationError(
                "ingestion exact cell lookup shard is invalid"
            ) from exc
        if len(records) != binding["record_count"]:
            raise ContractValidationError(
                "ingestion exact cell lookup shard count mismatch"
            )
        cache[key] = records
        return records
def _build_candidate_table_ledger(session: Any) -> dict[str, Any] | None:
    hashes = dict(session.authorized_observation_hashes)
    lineages = {
        item.source_observation_id: item
        for item in session.occurrence_lineages
        if isinstance(item, (MailAttachmentChildOccurrenceLineage, MailInlineTableOccurrenceLineage))
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
            key = (item.asset_id, item.location.get("parent_message_observation_id"),
                   item.location.get("mime_ordinal"), item.location.get("sheet_name"),
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
    supplemental_loaded = "supplemental_observation_partition_status" in safe_binding
    if supplemental_loaded:
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
    authorized_observation_hashes = dict(session.authorized_observation_hashes)
    rows = snapshot.get("parsed_mail_observations")
    if not isinstance(rows, list):
        raise ContractValidationError("production source occurrence inventory is unavailable")
    if any(not isinstance(row, Mapping) for row in rows):
        raise ContractValidationError("production source occurrence row is invalid")
    source_observation_ids = {row.get("observation_id") for row in rows}
    observation_by_id = {
        observation.observation_id: observation
        for observation in session.authorized_observations
    }
    table_parent_ids = {
        lineage.parent_attachment_observation_id
        for lineage in session.occurrence_lineages
        if isinstance(lineage, MailAttachmentChildOccurrenceLineage)
        and lineage.observation_type == "table_row"
    }
    supplemental_parent_ids: set[str] = set()
    item_lineage_by_occurrence: dict[str, str] = {}
    for lineage in session.occurrence_lineages:
        if not isinstance(lineage, MailMessageOccurrenceLineage):
            continue
        if lineage.source_observation_id not in source_observation_ids:
            parent = observation_by_id.get(lineage.source_observation_id)
            if (
                not supplemental_loaded
                or parent is None
                or parent.modality != "mail"
                or parent.observation_type != "email_attachment_occurrence"
                or parent.observation_id not in table_parent_ids
                or authorized_observation_hashes.get(parent.observation_id)
                != sha256_json(parent.to_dict())
            ):
                raise ContractValidationError(
                    "production direct source identifier occurrence scope is invalid"
                )
            # The separately sealed table partition has attachment parents, not
            # additional base-bundle mail inventory items. Child lineage and
            # table coverage remain validated by the table provider below.
            supplemental_parent_ids.add(parent.observation_id)
            continue
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
    for row in rows:
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
        or (
            not supplemental_loaded
            and (
                graph_build.identifier_mention_count
                != mention_batch.occurrence_count
                or graph_build.authorized_identifier_mention_count
                != mention_batch.occurrence_count
            )
        )
        or safe_binding["source_identifier_mention_batch_fingerprint"]
        != mention_batch.batch_fingerprint
    ):
        raise ContractValidationError(
            "production direct source identifier batch binding is invalid"
        )
    retrieval_observation_hashes = dict(session.retrieval_observation_hashes)
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
            if observation_id in supplemental_parent_ids:
                continue
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

    observation_by_hash = {
        observation_hash: observation_by_id[observation_id]
        for observation_id, observation_hash in authorized_observation_hashes.items()
        if observation_id in observation_by_id
    }

    def project_mail_occurrence(
        occurrence_id: str,
        bindings: set[tuple[str, str, str, str]],
    ) -> AuthorizedSourceOccurrence:
        projection: set[tuple[str, str, str, str]] = set()
        # Project only evidence already bound to this item. Do not manufacture
        # identifier bindings to pull in another Observation's readable fields.
        for citation_hash, lineage_hash in {binding[2:] for binding in bindings}:
            observation = observation_by_hash[citation_hash]
            lineage = lineage_by_observation_id[observation.observation_id]
            if (
                not isinstance(lineage, MailMessageOccurrenceLineage)
                or lineage.occurrence_id != occurrence_id
                or lineage.lineage_fingerprint != lineage_hash
            ):
                raise ContractValidationError(
                    "production mail projection lineage binding is invalid"
                )
            payload = observation.payload or {}
            fields: tuple[tuple[str, Any], ...] = ()
            if observation.observation_type == "email_message":
                fields = tuple(
                    (field, payload.get(field))
                    for field in ("subject", "sender", "sent_at")
                )
            elif observation.observation_type == "email_header":
                field = payload.get("header_name")
                if isinstance(field, str) and field.casefold() in {
                    "from", "sender", "to", "cc", "subject", "date",
                }:
                    fields = ((field, payload.get("header_value")),)
            elif observation.observation_type == "email_body_segment":
                fields = (("body_excerpt", observation.text),)
            for field, value in fields:
                if not isinstance(value, str) or not value:
                    continue
                safe_value, _ = redact_public_raw_references(value)
                projection.add((field, safe_value[:400], citation_hash, lineage_hash))
        return AuthorizedSourceOccurrence(
            item_hash=sha256_json(
                ["mail_message_occurrence", item_lineage_by_occurrence[occurrence_id]]
            ),
            value_bindings=tuple(sorted(bindings)),
            projection_bindings=tuple(sorted(projection)),
            structure_status="source_provided" if projection else None,
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
        if has_attachment_table_rows and not supplemental_loaded
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
                    project_mail_occurrence(occurrence_id, bindings)
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
            project_mail_occurrence(occurrence_id, bindings)
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
    if (
        supplemental_loaded
        and (table_row_provider is None or not table_row_provider.occurrences)
    ):
        raise ContractValidationError(
            "production supplemental table provider is unavailable"
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
    inline_tables: bool = False,
) -> SourceOccurrenceProvider | None:
    observations = tuple(session.authorized_observations)
    parents = tuple(
        observation
        for observation in observations
        if observation.observation_type == (
            "email_message" if inline_tables else "email_attachment_occurrence"
        )
    )
    rows = tuple(
        observation
        for observation in observations
        if observation.modality == "document"
        and observation.observation_type == "table_row"
        and (
            (observation.payload or {}).get("lineage", {}).get("source_family")
            == "mail_inline_table"
        ) == inline_tables
    )
    if not parents or not rows:
        return None
    authorized_hashes = dict(session.authorized_observation_hashes)
    lineage_by_id = {
        lineage.source_observation_id: lineage
        for lineage in session.occurrence_lineages
    }
    parent_by_child_asset: dict[str, Observation] = {}
    parent_by_id = {parent.observation_id: parent for parent in parents}
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
        parent = (
            parent_by_id.get((row.payload or {}).get("lineage", {}).get("parent_message_observation_id"))
            if inline_tables else parent_by_child_asset.get(row.asset_id or "")
        )
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
                and (
                    (cell.payload or {}).get("cell_state") == "absent"
                    or (cell.payload or {}).get("native", {}).get("explicit_blank") is True
                )
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
            if safe_value.strip():
                value_token_hashes.add(
                    source_occurrence_exact_cell_value_hash(
                        column_hash,
                        safe_value,
                    )
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
            if (
                structure_status == "source_provided"
                and cell_structure.get("structure_status") == "source_provided"
                and not tokenizer_profile.analyze(normalized_field).tokens
            ):
                # Preserve exact source labels that are grammar-only to the
                # tokenizer as schema candidates, never for candidate-only rows.
                column_candidate_hashes.add(sha256_json(normalized_field))
            phrase_surfaces = list(header_surfaces)
            if not phrase_surfaces or phrase_surfaces[-1] != normalized_field:
                phrase_surfaces.append(normalized_field)
            for start in range(len(phrase_surfaces)):
                for end in range(start + 1, min(len(phrase_surfaces), start + 4) + 1):
                    phrase = "".join(phrase_surfaces[start:end])
                    if phrase and tokenizer_profile.analyze(phrase).tokens:
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
                        "mail_inline_table_row_occurrence" if inline_tables else "attachment_table_row_occurrence",
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
    for parent in (() if inline_tables else parents):
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
        provider_id=("mail_inline_table_row_source_occurrence_provider_v1" if inline_tables
                     else "attachment_table_row_source_occurrence_provider_v1"),
        inventory_kind_alias="mail_inline_table_row" if inline_tables else "attachment_table_row",
        resource_kind="mail_inline_table_row_occurrence" if inline_tables else "attachment_table_row_occurrence",
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
        observation.location.get("parent_message_observation_id"),
        observation.location.get("mime_ordinal"),
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
    "build_mail_evidence_query_handler",
    "build_issue56_production_semantic_retrieval_handler",
    "load_issue56_sealed_source_diagnostic_input",
    "load_issue56_real_prompt_sealed_source_diagnostic_input",
    "load_issue56_relation_projection_equivalence_diagnostic_input",
    "load_issue56_relation_projection_equivalence_v6_diagnostic_input",
    "load_issue56_relation_projection_offline_equivalence_v7_diagnostic_input",
]
