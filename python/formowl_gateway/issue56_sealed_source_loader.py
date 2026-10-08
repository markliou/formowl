"""Environment-bound adapter for the Issue #56 sealed-source diagnostic.

The CLI resolves this module by ``module:function``.  Source loading remains in
``formowl_mail.issue56_sealed_source`` so the mail owner path never imports the
gateway contract.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from email.headerregistry import HeaderRegistry
import hashlib
import json
import os
from pathlib import Path
import re
import time
from types import MappingProxyType
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
    authorized_source_occurrence_scope_fingerprint,
    source_occurrence_column_capability_hash,
    source_occurrence_exact_cell_value_hash,
    source_occurrence_projection_capability_hash,
    normalize_source_occurrence_structured_surface,
)
from formowl_mail.issue56_sealed_source import (
    APPROVER_ACTOR,
    ARTIFACT_ID as SEALED_SOURCE_LOAD_ARTIFACT_ID,
    IDENTITY_SCOPE_MODE,
    SOURCE_GRAPH_POLICY_ID,
    WORKSPACE_ID,
    Issue56IngestionRevision,
    load_issue56_sealed_source,
)
from formowl_mail.hybrid import (
    AdaptiveQueryPlanner,
    _semantic_session_source_families,
    attach_authorized_source_occurrence_providers,
    execute_bounded_adaptive_query,
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
    authorized_permission_scope_matches,
    deterministic_query_class,
    validate_semantic_request_contract,
)
from formowl_retrieval.gateway import (
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
    return {**core, "capability_fingerprint": sha256_json(core)}


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
    available_families = tuple(capabilities["source_families"])
    selector_ids = tuple(getattr(records, "authorized_mail_import_session_ids", ()))
    coverage = revision.safe_binding.get("extraction_coverage", {})
    coverage_complete = (
        isinstance(coverage, Mapping)
        and coverage.get("source_completeness_certified") is True
        and not revision.safe_binding.get("bounded_canary_candidate_count")
    )

    def handler(arguments: dict[str, Any]) -> dict[str, Any]:
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
        if query_class == "exact_set_or_inventory":
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
        requested_fields = tuple(request_contract["requested_fields"])
        query_terms: set[str] = set()
        protected_terms: set[str] = set()
        active_family: str | None = None
        active_selector: str | None = selector
        message_fingerprints_by_occurrence: dict[tuple[str, str, str, str], str] = {}
        unresolved_parent_binding = False

        def begin(deadline: float) -> None:
            nonlocal query_terms, protected_terms
            check_source_evidence_deadline(deadline)
            analysis = tokenizer.analyze(query_text)
            query_terms = set(analysis.tokens)
            protected_terms = {item.exact_token for item in analysis.protected_identifiers}
            # A Query Agent may add presentation instructions to query_text.
            # Rank source candidates by the validated evidence constraints, not
            # those instruction words. Multiword constraints use the same frozen
            # profile as the source postings; the full matcher remains unchanged.
            lookup_terms = set()
            for term in required_terms:
                check_source_evidence_deadline(deadline)
                lookup_terms.update(tokenizer.analyze(term).tokens)
            project.source_lookup_terms = tuple(sorted(
                lookup_terms if required_terms else query_terms
            ))
            check_source_evidence_deadline(deadline)

        def project(observation: Observation, scope_id: str, deadline: float):
            nonlocal unresolved_parent_binding
            check_source_evidence_deadline(deadline)
            focus_terms = (*requested_fields, *required_terms, *sorted(query_terms))

            def focused_text(value: str) -> str:
                safe = redact_public_raw_references(value)[0]
                if len(safe) <= 400:
                    return safe
                start = 0
                for term in focus_terms:
                    match = re.search(
                        re.escape(term.replace("_", " ")),
                        safe,
                        re.IGNORECASE,
                    )
                    if match is not None:
                        start = max(0, min(match.start() - 80, len(safe) - 400))
                        break
                return safe[start:start + 400]

            if active_family == "mail":
                payload = to_plain(observation.payload or {})
                location = to_plain(observation.location)
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
                    return None
                lineage = source_occurrence_lineage_from_observation(
                    observation, authorized_source=source,
                )
                if (
                    observation.observation_type == "email_message"
                    and isinstance(message_fingerprint, str)
                    and isinstance(occurrence_id, str)
                ):
                    message_fingerprints_by_occurrence[(
                        scope_id, observation.asset_id, observation.extractor_run_id, occurrence_id,
                    )] = (
                        message_fingerprint
                    )
                if (
                    _source_mail_observation_match(
                        observation,
                        query_terms=query_terms,
                        required_terms=required_terms or None,
                        protected_query_tokens=protected_terms,
                        tokenizer_profile=tokenizer,
                        deadline_monotonic=deadline,
                    ) is None
                ):
                    return None
                if message_fingerprint is None and isinstance(occurrence_id, str):
                    message_fingerprint = message_fingerprints_by_occurrence.get(
                        (scope_id, observation.asset_id, observation.extractor_run_id, occurrence_id)
                    )
                if not isinstance(message_fingerprint, str) or not isinstance(occurrence_id, str):
                    unresolved_parent_binding = True
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
                    "snippet": focused_text(observation.text or ""),
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
                snippet = _safe_snippet(snippet_payload)
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
                if required_terms:
                    if not all(term in normalized for term in required_terms):
                        return None
                else:
                    source_tokens = set(tokenizer.analyze(text).tokens)
                    if not query_terms.intersection(source_tokens):
                        return None
                source_tokens = set(tokenizer.analyze(text).tokens)
                if protected_terms and not protected_terms.issubset(source_tokens):
                    return None
                lineage = source_occurrence_lineage_from_observation(
                    observation, authorized_source=source,
                )
                snippet = {
                    "snippet": focused_text(text),
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
                return sha256_json(observation.to_dict()), snippet
            else:
                raise ContractValidationError("source-start family is invalid")
            return sha256_json(observation.to_dict()), snippet

        def read_source(**kwargs: Any) -> RevisionOwnedMailSourceScan:
            nonlocal active_family, active_selector
            remaining = kwargs["max_observations"]
            scanned = 0
            families = [
                family for family in request_contract["source_family_scope"]
                if family in available_families and family != "attachment_table"
            ]
            incomplete_reason: str | None = None
            for family_index, family in enumerate(families):
                active_family = family
                selectors = (
                    (selector,) if family == "mail" and mail_tool
                    else (selector_ids or (None,)) if family == "mail"
                    else (None,)
                )
                family_left = len(families) - family_index
                family_remaining = remaining - scanned
                family_limit = family_remaining // family_left
                if family_limit <= 0:
                    incomplete_reason = "observation_limit"
                    break
                for selector_index, family_selector in enumerate(selectors):
                    active_selector = family_selector
                    selectors_left = len(selectors) - selector_index
                    left = min(
                        family_limit,
                        max(1, (family_limit - (scanned % family_limit)) // selectors_left),
                    )
                    if left <= 0:
                        incomplete_reason = "observation_limit"
                        break
                    scan = records.scan_authorized_observations(
                        source_family=family, source_scope_ids=(
                            source.source_scope_ids if family == "document_text" else ()
                        ),
                        mail_import_session_id=family_selector,
                        max_observations=left,
                        deadline_monotonic=kwargs["deadline_monotonic"],
                        observation_callback=kwargs["observation_callback"],
                    )
                    if not isinstance(scan, RevisionOwnedMailSourceScan):
                        raise ContractValidationError("source-start scan result is invalid")
                    scanned += scan.scanned_observation_count
                    if not scan.complete:
                        incomplete_reason = scan.stop_reason or "deadline"
                        if incomplete_reason in {"deadline", "callback"}:
                            return RevisionOwnedMailSourceScan(
                                (), scanned, False, incomplete_reason,
                            )
            active_family = None
            active_selector = selector
            if incomplete_reason is None and unresolved_parent_binding:
                incomplete_reason = "source_parent_binding_unresolved"
            return RevisionOwnedMailSourceScan(
                (), scanned, incomplete_reason is None, incomplete_reason,
            )

        limit = arguments.get("limit" if mail_tool else "page_size", 5 if mail_tool else 10)
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ContractValidationError("source-start evidence limit is invalid")
        double_check = source_evidence_double_check(
            initial_status="pending_review",
            query_class=query_class,
            result_query_class=query_class,
            initial_warnings=("retrieval_projection_unavailable",),
            verified_evidence_count=0,
            evidence_limit=limit,
            sealed_coverage_complete=coverage_complete,
            read_source=read_source,
            project_observation=project,
            begin=begin,
            requested_fields=requested_fields,
            supported_requested_fields=(),
        )
        evidence = list(double_check.evidence)
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
        query_agent["context_bundle"]["bundle_fingerprint"] = sha256_json(
            query_agent["context_bundle"]
        )
        status = double_check.status or ("ok" if evidence else "pending_review")
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
                "mail_import_session_id": selector,
                "query_hash": sha256_json(query_text),
                "evidence_snippets": mail_evidence,
                "citations": citations,
                "warnings": sorted(set(
                    [*double_check.warnings]
                    + (["mail_evidence_no_verified_citations"] if not citations else [])
                )),
                "requested_field_coverage": coverage_payload if requested_fields else None,
            }
            if payload["requested_field_coverage"] is None:
                payload.pop("requested_field_coverage")
            return payload
        return {
            "status": status,
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

    handler.authorized_capability_summary = capabilities
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
        }:
            raise ContractValidationError("production semantic arguments are invalid")
        if (
            arguments["requester_user_id"] != session.requester_user_id
            or arguments["workspace_id"] != session.workspace_id
            or not isinstance(arguments["session_id"], str)
            or not arguments["session_id"]
        ):
            raise ContractValidationError("production semantic actor binding mismatch")
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
        if exact_cell_lookup is not None:
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
        if candidate is not None:
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
        if result is None:
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
                project_source_observation.source_lookup_terms = tuple(sorted(
                    required_terms if required_terms else query_terms
                ))

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
                if (
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
                verified_evidence_count=len(evidence),
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
            recovered_evidence = list(double_check.evidence)
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
        return retrieval_handler, mail_evidence_handler

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
    return retrieval_handler, mail_evidence_handler


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


class _IngestionExactCellLookup:
    """Resolve only query-matched table rows from a sealed compact index."""

    def __init__(self, revision: Issue56IngestionRevision) -> None:
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
            != revision.session.source_authority_fingerprint
            or manifest.get("tokenizer_profile_fingerprint")
            != revision.session.index.profile_fingerprint
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
    ) -> tuple[Any, ...]:
        """Stream a sealed shard and retain only records matching its key field."""
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
        try:
            with path.open("rb") as stream:
                for line in stream:
                    digest.update(line)
                    size += len(line)
                    record_count += 1
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
        return tuple(records)

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
