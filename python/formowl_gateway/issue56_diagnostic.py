"""Non-claim-bearing Issue #56 prompt-to-MCP diagnostic composition.

The existing synthetic fixture remains available.  The versioned sealed-source
mode accepts only a validated loader result and still uses the same connected
MCP HTTP boundary.  Neither mode reads UAT/holdout material, configures a
production store, or expands the production connected-tool policy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import secrets
import time
from types import MappingProxyType
from typing import Any

from formowl_auth.models import OAuthAccessDenied, OAuthPrincipal
from formowl_auth.provider import ActorContext
from formowl_contract import (
    ContractValidationError,
    Observation,
    SessionIdentity,
    User,
    WorkspaceMember,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_graph import EffectiveGraphView
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode
from formowl_mail import (
    ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
    build_authorized_semantic_mail_session,
    build_mail_evidence_bundle,
    render_governed_evidence_answer,
)
from formowl_mail.hybrid import AuthorizedSemanticMailSession, SemanticPhaseTrace
from mcp import types as mcp_types
from mcp.shared.version import LATEST_PROTOCOL_VERSION

from .remote import (
    ConnectedMcpApplication,
    RemoteMcpDispatcher,
    build_remote_tool_descriptors,
    create_connected_mcp_application,
)
from .semantic import SemanticMcpGateway, validate_public_gateway_payload


ISSUE56_DIAGNOSTIC_ARTIFACT_ID = "formowl_issue56_prompt_mcp_hybrid_diagnostic_v1"
ISSUE56_DIAGNOSTIC_SCHEMA_VERSION = 1
ISSUE56_DIAGNOSTIC_CLAIM_STATUS = "blocked_non_claim_bearing_diagnostic_only"
ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE = "workspace_only_v1"
ISSUE56_DIAGNOSTIC_WORKSPACE_ID = "workspace_formowl"
ISSUE56_DIAGNOSTIC_USER_ID = "user_full_pst_domain_hard_case_eval_owner"
ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT = "PO470002002 與 ORIGIN-TAIWAN-01 的關係"
ISSUE56_DIAGNOSTIC_TOOL_NAME = "query_effective_graph_view"
ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID = "issue56-synthetic-prompt-mcp-hybrid-diagnostic-20260820-v1"
ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID = (
    "issue56-sealed-source-phase-traced-diagnostic-20260820-v1"
)
ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID = (
    "issue56-sealed-source-phase-traced-diagnostic-20260821-v2"
)
ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID = (
    "issue56-sealed-source-phase-traced-diagnostic-20260821-v3"
)
ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V3_MODE_ID = ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID = (
    "issue56-sealed-source-real-prompt-phase-traced-diagnostic-20260823-v4"
)
ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID = (
    "issue56-sealed-source-real-prompt-relation-projection-equivalence-"
    "phase-traced-diagnostic-20260825-v5"
)
ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID = (
    "issue56-sealed-source-real-prompt-relation-projection-equivalence-"
    "phase-traced-diagnostic-20260825-v6"
)
ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID = (
    "issue56-sealed-source-real-prompt-relation-projection-offline-equivalence-"
    "phase-traced-diagnostic-20260825-v7"
)
_ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID = (
    "issue56-internal-test-relation-projection-equivalence-phase-traced-v0"
)
_ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID = (
    "issue56-internal-test-relation-projection-equivalence-phase-traced-v6"
)
_ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID = (
    "issue56-internal-test-relation-projection-offline-equivalence-phase-traced-v7"
)
ISSUE56_SEALED_SOURCE_DIAGNOSTIC_PROMPT = ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT
ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID = "issue56_sealed_source_diagnostic_loader_v3"
ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID = (
    "issue56_real_prompt_sealed_source_diagnostic_loader_v4"
)
ISSUE56_RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_ID = (
    "issue56_relation_projection_equivalence_diagnostic_loader_v5"
)
ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_ID = (
    "issue56_relation_projection_equivalence_diagnostic_loader_v6"
)
ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID = (
    "issue56_relation_projection_offline_equivalence_diagnostic_loader_v7"
)

_REAL_PROMPT_DIAGNOSTIC_MODE_IDS = frozenset(
    {
        ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }
)
_RELATION_PROJECTION_EQUIVALENCE_MODE_IDS = frozenset(
    {
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }
)
_RELATION_PROJECTION_EQUIVALENCE_V6_MODE_IDS = frozenset(
    {
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
    }
)
_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_MODE_IDS = frozenset(
    {
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }
)

_CREATED_AT = "2026-08-20T08:00:00+00:00"
_RESOURCE = "https://issue56-diagnostic.formowl.invalid/mcp"
_SYNTHETIC_BEARER = "issue56.synthetic.connected.bearer"
_TOKEN_SESSION_ID = "oauthsid_issue56_prompt_mcp"
_ALLOWED_RELATIONS = ("origin_in", "supplied_by")
_DIAGNOSTIC_WORKSPACE_SCOPE = {
    "scope_type": "workspace",
    "scope_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    "visibility": "restricted",
}
_SUPPORTED_SEALED_SOURCE_PERMISSION_SCOPE_TYPES = frozenset(
    {
        "mail_import_session",
        "project",
        "workspace",
    }
)
_SEALED_SOURCE_PERMISSION_SCOPE_REQUIRED_FIELDS = frozenset(
    {
        "scope_id",
        "scope_type",
        "visibility",
    }
)
_SEALED_SOURCE_PERMISSION_SCOPE_OPTIONAL_FIELDS = frozenset({"inherited_from"})
_EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE = "_formowl_issue56_effective_graph_content_snapshot_v1"


@dataclass(frozen=True)
class Issue56DiagnosticConfig:
    issuer: str = "https://issue56-diagnostic.formowl.invalid"
    resource: str = _RESOURCE
    scopes: tuple[str, ...] = ("formowl.use",)
    chatgpt_callback_mode: str = "production_exact"

    @property
    def protected_resource_metadata_url(self) -> str:
        return f"{self.issuer}/.well-known/oauth-protected-resource"


@dataclass(frozen=True)
class Issue56DiagnosticPhase:
    phase: str
    status: str
    elapsed_ms: float

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True)
class Issue56SealedSourceDiagnosticInput:
    """Validated Worker-A handoff consumed by the sealed diagnostic.

    A loader has the zero-argument signature
    ``() -> Issue56SealedSourceDiagnosticInput``.  It owns source-asset loading
    and seal validation; this boundary independently revalidates the authorized
    session, graph view, inventory, scope, and derived fingerprints.
    """

    session: AuthorizedSemanticMailSession = field(repr=False)
    effective_graph_view: EffectiveGraphView = field(repr=False)
    allowed_relation_types: tuple[str, ...]
    source_asset_fingerprint: str
    loader_contract_fingerprint: str
    observation_inventory_fingerprint: str
    permission_lineage_fingerprint: str
    effective_graph_view_fingerprint: str
    graph_revision_fingerprint: str
    source_loader_binding_fingerprint: str
    source_binding_fingerprint: str
    observation_count: int
    lineage_crosswalk_precompute: Issue56LineageCrosswalkPrecomputeEvidence
    relation_projection_base_precompute: Issue56RelationProjectionBasePrecomputeEvidence
    private_prompt: str | None = field(default=None, repr=False, compare=False)
    prompt_selection: Issue56SourceBackedPromptSelectionEvidence | None = None
    diagnostic_mode_id: str = ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID


@dataclass(frozen=True)
class Issue56SourceBackedPromptSelectionEvidence:
    """Safe proof for one private, source-backed connected-pair prompt."""

    status: str
    prompt_hash: str
    source_loader_binding_fingerprint: str
    permission_fingerprint: str
    index_fingerprint: str
    graph_revision_fingerprint: str
    lexical_anchor_count: int
    selected_identifier_count: int
    authorized_connected_graph_path_count: int
    supporting_observation_count: int
    owner_selection_proof_fingerprint: str
    owner_selection_proof: Mapping[str, Any]
    selection_proof_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": ("formowl_issue56_real_prompt_gateway_selection_binding_v1"),
            "schema_version": 1,
            "status": self.status,
            "prompt_hash": self.prompt_hash,
            "source_loader_binding_fingerprint": (self.source_loader_binding_fingerprint),
            "permission_fingerprint": self.permission_fingerprint,
            "owner_selection_proof": dict(self.owner_selection_proof),
            "selection_proof_fingerprint": self.selection_proof_fingerprint,
            "counts": {
                "lexical_anchor_count": self.lexical_anchor_count,
                "selected_identifier_count": self.selected_identifier_count,
                "authorized_connected_graph_path_count": (
                    self.authorized_connected_graph_path_count
                ),
                "supporting_observation_count": self.supporting_observation_count,
            },
        }


@dataclass(frozen=True)
class Issue56LineageCrosswalkPrecomputeEvidence:
    """Hash/count/timing-only evidence from Worker A's one cold precompute."""

    status: str
    cache_status: str
    helper_invocation_count: int
    elapsed_ms: float
    crosswalk_fingerprint: str
    index_fingerprint: str
    graph_revision_fingerprint: str
    cache_key_fingerprint: str
    authorized_evidence_count: int
    indexed_evidence_count: int
    occurrence_bound_evidence_count: int
    graph_node_bound_evidence_count: int
    graph_edge_bound_evidence_count: int
    evidence_binding_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "formowl_issue56_lineage_crosswalk_precompute_safe_v1",
            "schema_version": 1,
            "status": self.status,
            "cache_status": self.cache_status,
            "helper_invocation_count": self.helper_invocation_count,
            "elapsed_ms": self.elapsed_ms,
            "crosswalk_fingerprint": self.crosswalk_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "cache_key_fingerprint": self.cache_key_fingerprint,
            "evidence_binding_fingerprint": self.evidence_binding_fingerprint,
            "counts": {
                "authorized_evidence_count": self.authorized_evidence_count,
                "indexed_evidence_count": self.indexed_evidence_count,
                "occurrence_bound_evidence_count": self.occurrence_bound_evidence_count,
                "graph_node_bound_evidence_count": self.graph_node_bound_evidence_count,
                "graph_edge_bound_evidence_count": self.graph_edge_bound_evidence_count,
            },
        }


@dataclass(frozen=True)
class Issue56RelationProjectionBasePrecomputeEvidence:
    """Hash/count/timing-only evidence from Worker A's one cold base precompute."""

    status: str
    cache_status: str
    helper_invocation_count: int
    elapsed_ms: float
    cache_binding_fingerprint: str
    index_fingerprint: str
    graph_revision_fingerprint: str
    candidate_admission_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    authorized_observation_count: int
    candidate_count: int
    projected_node_count: int
    observation_bound_node_group_count: int
    adjacency_node_count: int
    adjacency_transition_count: int
    authorized_index_vocabulary_hash_count: int
    authorized_graph_vocabulary_hash_count: int
    precompute_fingerprint: str
    evidence_binding_fingerprint: str

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": "formowl_issue56_relation_projection_base_precompute_v1",
            "schema_version": 1,
            "status": self.status,
            "cache_status": self.cache_status,
            "helper_invocation_count": self.helper_invocation_count,
            "elapsed_ms": self.elapsed_ms,
            "cache_binding_fingerprint": self.cache_binding_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "precompute_fingerprint": self.precompute_fingerprint,
            "evidence_binding_fingerprint": self.evidence_binding_fingerprint,
            "counts": {
                "authorized_observation_count": self.authorized_observation_count,
                "candidate_count": self.candidate_count,
                "projected_node_count": self.projected_node_count,
                "observation_bound_node_group_count": (self.observation_bound_node_group_count),
                "adjacency_node_count": self.adjacency_node_count,
                "adjacency_transition_count": self.adjacency_transition_count,
                "authorized_index_vocabulary_hash_count": (
                    self.authorized_index_vocabulary_hash_count
                ),
                "authorized_graph_vocabulary_hash_count": (
                    self.authorized_graph_vocabulary_hash_count
                ),
            },
        }


@dataclass(frozen=True)
class Issue56GraphContentPresealEvidence:
    """Safe proof that v6 isolates graph content from relation caches."""

    status: str
    cache_status: str
    helper_invocation_count: int
    before_preseal_elapsed_ms: float
    after_snapshot_validation_elapsed_ms: float
    session_binding_fingerprint: str
    source_access_fingerprint: str
    source_binding_fingerprint: str
    permission_lineage_fingerprint: str
    effective_graph_view_fingerprint: str
    graph_revision_fingerprint: str
    graph_content_fingerprint: str
    index_fingerprint: str
    candidate_admission_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    owner_precompute_fingerprint: str
    authorized_observation_count: int
    source_scope_count: int
    node_count: int
    edge_count: int
    access_required_count: int
    applied_grant_count: int
    before_binding_cache_entry_count: int
    before_base_cache_entry_count: int
    after_binding_cache_entry_count: int
    after_base_cache_entry_count: int
    evidence_binding_fingerprint: str

    def _binding_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": "formowl_issue56_graph_content_preseal_safe_v1",
            "schema_version": 1,
            "status": self.status,
            "cache_status": self.cache_status,
            "helper_invocation_count": self.helper_invocation_count,
            "before_preseal_elapsed_ms": self.before_preseal_elapsed_ms,
            "after_snapshot_validation_elapsed_ms": (self.after_snapshot_validation_elapsed_ms),
            "session_binding_fingerprint": self.session_binding_fingerprint,
            "source_access_fingerprint": self.source_access_fingerprint,
            "source_binding_fingerprint": self.source_binding_fingerprint,
            "permission_lineage_fingerprint": self.permission_lineage_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "graph_content_fingerprint": self.graph_content_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "owner_precompute_fingerprint": self.owner_precompute_fingerprint,
            "authorized_observation_count": self.authorized_observation_count,
            "source_scope_count": self.source_scope_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "access_required_count": self.access_required_count,
            "applied_grant_count": self.applied_grant_count,
            "before_binding_cache_entry_count": (self.before_binding_cache_entry_count),
            "before_base_cache_entry_count": self.before_base_cache_entry_count,
            "after_binding_cache_entry_count": self.after_binding_cache_entry_count,
            "after_base_cache_entry_count": self.after_base_cache_entry_count,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        binding_payload = self._binding_payload()
        if self.evidence_binding_fingerprint != sha256_json(binding_payload):
            raise ContractValidationError("graph content preseal evidence seal mismatch")
        return {
            "artifact_id": "formowl_issue56_graph_content_preseal_safe_v1",
            "schema_version": 1,
            "status": self.status,
            "cache_status": self.cache_status,
            "helper_invocation_count": self.helper_invocation_count,
            "session_binding_fingerprint": self.session_binding_fingerprint,
            "source_access_fingerprint": self.source_access_fingerprint,
            "source_binding_fingerprint": self.source_binding_fingerprint,
            "permission_lineage_fingerprint": self.permission_lineage_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "graph_content_fingerprint": self.graph_content_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "owner_precompute_fingerprint": self.owner_precompute_fingerprint,
            "isolation": {
                "snapshot_objects": "isolated",
                "locks": "isolated",
                "binding_cache_containers": "isolated",
                "base_cache_containers": "isolated",
            },
            "timing": {
                "before_preseal_elapsed_ms": self.before_preseal_elapsed_ms,
                "after_snapshot_validation_elapsed_ms": (self.after_snapshot_validation_elapsed_ms),
            },
            "counts": {
                "before_binding_cache_entry_count": (self.before_binding_cache_entry_count),
                "before_base_cache_entry_count": self.before_base_cache_entry_count,
                "after_binding_cache_entry_count": (self.after_binding_cache_entry_count),
                "after_base_cache_entry_count": self.after_base_cache_entry_count,
                "authorized_observation_count": self.authorized_observation_count,
                "source_scope_count": self.source_scope_count,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "access_required_count": self.access_required_count,
                "applied_grant_count": self.applied_grant_count,
            },
            "evidence_binding_fingerprint": self.evidence_binding_fingerprint,
        }


@dataclass(frozen=True)
class Issue56OfflineEquivalencePreflightEvidence:
    """Safe proof that v7 has two cold-presealed isolated graph views."""

    status: str
    cache_status: str
    graph_preseal_helper_invocation_count: int
    after_relation_precompute_helper_invocation_count: int
    cold_graph_preseal_elapsed_ms: float
    after_graph_preseal_elapsed_ms: float
    after_relation_precompute_elapsed_ms: float
    session_binding_fingerprint: str
    source_access_fingerprint: str
    source_binding_fingerprint: str
    permission_lineage_fingerprint: str
    effective_graph_view_fingerprint: str
    graph_revision_fingerprint: str
    graph_content_fingerprint: str
    index_fingerprint: str
    candidate_admission_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    cold_graph_preseal_fingerprint: str
    after_graph_preseal_fingerprint: str
    relation_projection_precompute_fingerprint: str
    relation_projection_cache_binding_fingerprint: str
    authorized_observation_count: int
    source_scope_count: int
    node_count: int
    edge_count: int
    access_required_count: int
    applied_grant_count: int
    cold_binding_cache_entry_count: int
    cold_base_cache_entry_count: int
    after_binding_cache_entry_count: int
    after_base_cache_entry_count: int
    evidence_binding_fingerprint: str

    def _binding_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": (
                "formowl_issue56_relation_projection_offline_equivalence_preflight_safe_v1"
            ),
            "schema_version": 1,
            "status": self.status,
            "cache_status": self.cache_status,
            "graph_preseal_helper_invocation_count": (self.graph_preseal_helper_invocation_count),
            "after_relation_precompute_helper_invocation_count": (
                self.after_relation_precompute_helper_invocation_count
            ),
            "cold_graph_preseal_elapsed_ms": self.cold_graph_preseal_elapsed_ms,
            "after_graph_preseal_elapsed_ms": self.after_graph_preseal_elapsed_ms,
            "after_relation_precompute_elapsed_ms": (self.after_relation_precompute_elapsed_ms),
            "session_binding_fingerprint": self.session_binding_fingerprint,
            "source_access_fingerprint": self.source_access_fingerprint,
            "source_binding_fingerprint": self.source_binding_fingerprint,
            "permission_lineage_fingerprint": self.permission_lineage_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "graph_content_fingerprint": self.graph_content_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "cold_graph_preseal_fingerprint": self.cold_graph_preseal_fingerprint,
            "after_graph_preseal_fingerprint": self.after_graph_preseal_fingerprint,
            "relation_projection_precompute_fingerprint": (
                self.relation_projection_precompute_fingerprint
            ),
            "relation_projection_cache_binding_fingerprint": (
                self.relation_projection_cache_binding_fingerprint
            ),
            "authorized_observation_count": self.authorized_observation_count,
            "source_scope_count": self.source_scope_count,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "access_required_count": self.access_required_count,
            "applied_grant_count": self.applied_grant_count,
            "cold_binding_cache_entry_count": self.cold_binding_cache_entry_count,
            "cold_base_cache_entry_count": self.cold_base_cache_entry_count,
            "after_binding_cache_entry_count": self.after_binding_cache_entry_count,
            "after_base_cache_entry_count": self.after_base_cache_entry_count,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        binding_payload = self._binding_payload()
        if self.evidence_binding_fingerprint != sha256_json(binding_payload):
            raise ContractValidationError("offline equivalence preflight evidence seal mismatch")
        safe = {
            "artifact_id": binding_payload["artifact_id"],
            "schema_version": binding_payload["schema_version"],
            "status": self.status,
            "cache_status": self.cache_status,
            "session_binding_fingerprint": self.session_binding_fingerprint,
            "source_access_fingerprint": self.source_access_fingerprint,
            "source_binding_fingerprint": self.source_binding_fingerprint,
            "permission_lineage_fingerprint": self.permission_lineage_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "graph_content_fingerprint": self.graph_content_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "cold_graph_preseal_fingerprint": self.cold_graph_preseal_fingerprint,
            "after_graph_preseal_fingerprint": self.after_graph_preseal_fingerprint,
            "relation_projection_precompute_fingerprint": (
                self.relation_projection_precompute_fingerprint
            ),
            "relation_projection_cache_binding_fingerprint": (
                self.relation_projection_cache_binding_fingerprint
            ),
            "isolation": {
                "view_objects": "isolated",
                "snapshot_objects": "isolated",
                "locks": "isolated",
                "binding_cache_containers": "isolated",
                "base_cache_containers": "isolated",
            },
            "timing": {
                "cold_graph_preseal_elapsed_ms": self.cold_graph_preseal_elapsed_ms,
                "after_graph_preseal_elapsed_ms": self.after_graph_preseal_elapsed_ms,
                "after_relation_precompute_elapsed_ms": (self.after_relation_precompute_elapsed_ms),
            },
            "counts": {
                "graph_preseal_helper_invocation_count": (
                    self.graph_preseal_helper_invocation_count
                ),
                "after_relation_precompute_helper_invocation_count": (
                    self.after_relation_precompute_helper_invocation_count
                ),
                "authorized_observation_count": self.authorized_observation_count,
                "source_scope_count": self.source_scope_count,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "access_required_count": self.access_required_count,
                "applied_grant_count": self.applied_grant_count,
                "cold_binding_cache_entry_count": (self.cold_binding_cache_entry_count),
                "cold_base_cache_entry_count": self.cold_base_cache_entry_count,
                "after_binding_cache_entry_count": (self.after_binding_cache_entry_count),
                "after_base_cache_entry_count": self.after_base_cache_entry_count,
            },
            "evidence_binding_fingerprint": self.evidence_binding_fingerprint,
        }
        _assert_no_legacy_identity_fields(safe)
        assert_no_public_raw_references(
            safe,
            "issue56_relation_projection_offline_equivalence_preflight",
        )
        return safe


@dataclass(frozen=True)
class Issue56OfflineRelationPrecomputeEvidence:
    """Safe owner evidence for one post-claim unbudgeted cold cache prime."""

    status: str
    cache_status: str
    helper_invocation_count: int
    query_executed: bool
    binding_snapshot_status: str
    base_builder_status: str
    binding_snapshot_elapsed_ms: float
    base_builder_elapsed_ms: float
    total_elapsed_ms: float
    binding_entry_count_before: int
    binding_entry_count_after: int
    base_entry_count_before: int
    base_entry_count_after: int
    cache_binding_fingerprint: str
    graph_revision_fingerprint: str
    effective_graph_view_fingerprint: str
    index_fingerprint: str
    candidate_admission_profile_fingerprint: str
    authorized_observation_set_fingerprint: str
    candidate_set_fingerprint: str
    precompute_fingerprint: str
    owner_evidence_fingerprint: str
    evidence_binding_fingerprint: str

    def _binding_payload(self) -> dict[str, Any]:
        return {
            "artifact_id": ("formowl_issue56_relation_projection_offline_precompute_safe_v1"),
            "schema_version": 1,
            "status": self.status,
            "cache_status": self.cache_status,
            "helper_invocation_count": self.helper_invocation_count,
            "query_executed": self.query_executed,
            "binding_snapshot_status": self.binding_snapshot_status,
            "base_builder_status": self.base_builder_status,
            "binding_snapshot_elapsed_ms": self.binding_snapshot_elapsed_ms,
            "base_builder_elapsed_ms": self.base_builder_elapsed_ms,
            "total_elapsed_ms": self.total_elapsed_ms,
            "binding_entry_count_before": self.binding_entry_count_before,
            "binding_entry_count_after": self.binding_entry_count_after,
            "base_entry_count_before": self.base_entry_count_before,
            "base_entry_count_after": self.base_entry_count_after,
            "cache_binding_fingerprint": self.cache_binding_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "precompute_fingerprint": self.precompute_fingerprint,
            "owner_evidence_fingerprint": self.owner_evidence_fingerprint,
        }

    def to_safe_dict(self) -> dict[str, Any]:
        payload = self._binding_payload()
        if self.evidence_binding_fingerprint != sha256_json(payload):
            raise ContractValidationError("offline relation precompute evidence seal mismatch")
        safe = {
            "artifact_id": payload["artifact_id"],
            "schema_version": payload["schema_version"],
            "status": self.status,
            "cache_status": self.cache_status,
            "helper_invocation_count": self.helper_invocation_count,
            "query_executed": self.query_executed,
            "phases": {
                "binding_snapshot": {
                    "status": self.binding_snapshot_status,
                    "elapsed_ms": self.binding_snapshot_elapsed_ms,
                },
                "base_builder": {
                    "status": self.base_builder_status,
                    "elapsed_ms": self.base_builder_elapsed_ms,
                },
            },
            "total_elapsed_ms": self.total_elapsed_ms,
            "cache": {
                "binding_entry_count_before": self.binding_entry_count_before,
                "binding_entry_count_after": self.binding_entry_count_after,
                "base_entry_count_before": self.base_entry_count_before,
                "base_entry_count_after": self.base_entry_count_after,
            },
            "cache_binding_fingerprint": self.cache_binding_fingerprint,
            "graph_revision_fingerprint": self.graph_revision_fingerprint,
            "effective_graph_view_fingerprint": self.effective_graph_view_fingerprint,
            "index_fingerprint": self.index_fingerprint,
            "candidate_admission_profile_fingerprint": (
                self.candidate_admission_profile_fingerprint
            ),
            "authorized_observation_set_fingerprint": (self.authorized_observation_set_fingerprint),
            "candidate_set_fingerprint": self.candidate_set_fingerprint,
            "precompute_fingerprint": self.precompute_fingerprint,
            "owner_evidence_fingerprint": self.owner_evidence_fingerprint,
            "evidence_binding_fingerprint": self.evidence_binding_fingerprint,
        }
        _assert_no_legacy_identity_fields(safe)
        assert_no_public_raw_references(
            safe,
            "issue56_relation_projection_offline_precompute",
        )
        return safe


@dataclass
class Issue56DiagnosticState:
    phases: list[Issue56DiagnosticPhase] = field(default_factory=list)
    boundary_events: list[str] = field(default_factory=list)
    authentication_count: int = 0
    actor_resolution_count: int = 0
    authorization_decision_count: int = 0
    authorization_denial_count: int = 0
    semantic_handler_count: int = 0
    hybrid_query_count: int = 0
    answer_render_count: int = 0
    handler_argument_fingerprint: str | None = None
    handler_requester_user_id: str | None = field(default=None, repr=False)
    handler_workspace_id: str | None = field(default=None, repr=False)
    handler_session_id: str | None = field(default=None, repr=False)
    last_semantic_phase_trace: dict[str, Any] | None = None
    lineage_crosswalk_precompute_count: int = 0
    lineage_crosswalk_precompute_elapsed_ms: float | None = None
    lineage_crosswalk_cache_hit_status: str = "not_exercised"
    lineage_crosswalk_query_binding_status: str = "not_exercised"
    precomputed_lineage_crosswalk_fingerprint: str | None = field(
        default=None,
        repr=False,
    )
    relation_projection_base_precompute_count: int = 0
    relation_projection_base_precompute_elapsed_ms: float | None = None
    relation_projection_base_cache_status: str = "not_exercised"
    last_semantic_equivalence: dict[str, Any] | None = None

    @contextmanager
    def measure(self, phase: str) -> Iterator[None]:
        started_at = time.perf_counter()
        status = "passed"
        try:
            yield
        except Exception:
            status = "failed"
            raise
        finally:
            elapsed_ms = round((time.perf_counter() - started_at) * 1_000.0, 6)
            self.phases.append(
                Issue56DiagnosticPhase(
                    phase=phase,
                    status=status,
                    elapsed_ms=max(0.0, elapsed_ms),
                )
            )

    def safe_phase_trace(self) -> list[dict[str, Any]]:
        return [phase.to_safe_dict() for phase in self.phases]


@dataclass(frozen=True)
class _DiagnosticToolPolicy:
    allowed_roles: frozenset[str]
    requires_grant: bool


class Issue56DiagnosticOAuthBridge:
    """Deterministic OAuth bridge which never retains the raw bearer."""

    def __init__(
        self,
        *,
        config: Issue56DiagnosticConfig,
        google_client: object,
        state: Issue56DiagnosticState,
        actor_workspace_id: str = ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    ) -> None:
        self.config = config
        self.google_client = google_client
        self.state = state
        self.principal = OAuthPrincipal(
            user_id=ISSUE56_DIAGNOSTIC_USER_ID,
            external_identity_id="ext_issue56_workspace_owner",
            oauth_client_id="chatgpt_issue56_diagnostic",
            token_session_id=_TOKEN_SESSION_ID,
            scopes=("formowl.use",),
            resource=config.resource,
        )
        user = User(
            user_id=ISSUE56_DIAGNOSTIC_USER_ID,
            display_name="Issue 56 Diagnostic Owner",
            status="active",
            created_at=_CREATED_AT,
        )
        membership = WorkspaceMember(
            workspace_id=actor_workspace_id,
            user_id=ISSUE56_DIAGNOSTIC_USER_ID,
            role="owner",
        )
        self.actor_context = ActorContext(
            user=user,
            session_identity=SessionIdentity(
                session_id=_TOKEN_SESSION_ID,
                selected_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
                selected_at=_CREATED_AT,
                selection_method="google_oidc_oauth",
            ),
            workspace_memberships=[membership],
            current_workspace_id=actor_workspace_id,
            current_workspace_role="owner",
            external_identity_id=self.principal.external_identity_id,
            oauth_client_id=self.principal.oauth_client_id,
            oauth_token_session_id=_TOKEN_SESSION_ID,
            auth_mode="google_oidc_oauth",
            production_authentication=True,
            authentication_note="synthetic_connected_diagnostic_principal",
        )

    def authenticate_access_token(
        self,
        raw_token: str,
        *,
        required_scope: str,
        resource: str,
        now: datetime,
    ) -> OAuthPrincipal:
        del now
        with self.state.measure("bearer_authentication"):
            self.state.authentication_count += 1
            self.state.boundary_events.append("bearer_authentication")
            if (
                not secrets.compare_digest(raw_token, _SYNTHETIC_BEARER)
                or required_scope != "formowl.use"
                or resource != self.config.resource
            ):
                raise OAuthAccessDenied("invalid_token", "diagnostic_bearer_rejected", 401)
            return self.principal

    def resolve_actor_context(
        self,
        principal: OAuthPrincipal,
        *,
        now: datetime,
    ) -> ActorContext:
        del now
        with self.state.measure("actor_context_resolution"):
            self.state.actor_resolution_count += 1
            self.state.boundary_events.append("actor_context_resolution")
            if principal != self.principal:
                raise OAuthAccessDenied("invalid_token", "diagnostic_principal_mismatch", 401)
            return self.actor_context

    def record_mcp_authorization_decision(self, **values: Any) -> dict[str, Any]:
        with self.state.measure("dispatcher_authorization_audit"):
            self.state.authorization_decision_count += 1
            if not values.get("allowed"):
                self.state.authorization_denial_count += 1
            self.state.boundary_events.append(
                "dispatcher_authorized" if values.get("allowed") else "dispatcher_denied"
            )
        return {"status": "ok"}

    def record_mcp_http_authentication_denial(self, **values: Any) -> dict[str, Any]:
        values.pop("raw_token", None)
        self.state.authorization_denial_count += 1
        self.state.boundary_events.append("http_authentication_denied")
        return {"status": "ok"}

    def whoami_payload(self, actor_context: ActorContext) -> dict[str, Any]:
        return {
            "user_id": actor_context.user.user_id,
            "display_name": actor_context.user.display_name,
            "current_workspace": {
                "workspace_id": actor_context.current_workspace_id,
                "role": actor_context.current_workspace_role,
            },
            "auth_mode": "google_oidc_oauth",
        }


class _Issue56DiagnosticDispatcher(RemoteMcpDispatcher):
    """Instance-local read-only policy without changing production policy."""

    def __init__(
        self,
        *,
        bridge: Issue56DiagnosticOAuthBridge,
        config: Issue56DiagnosticConfig,
        semantic_gateway: SemanticMcpGateway,
        clock: Any,
    ) -> None:
        # Super validates the production-safe whoami-only configuration first.
        super().__init__(
            bridge=bridge,
            config=config,
            semantic_gateway=semantic_gateway,
            clock=clock,
            enabled_tool_names={"whoami"},
        )
        self.enabled_tool_names = frozenset({"whoami", ISSUE56_DIAGNOSTIC_TOOL_NAME})
        self.tool_policies = MappingProxyType(
            {
                "whoami": _DiagnosticToolPolicy(
                    allowed_roles=frozenset({"owner", "member", "viewer"}),
                    requires_grant=False,
                ),
                ISSUE56_DIAGNOSTIC_TOOL_NAME: _DiagnosticToolPolicy(
                    allowed_roles=frozenset({"owner"}),
                    requires_grant=False,
                ),
            }
        )

    async def list_tools(self) -> list[mcp_types.Tool]:
        descriptors = build_remote_tool_descriptors(
            required_scope=self.required_scope,
            enabled_tool_names={"whoami"},
        )
        schemes = [{"type": "oauth2", "scopes": [self.required_scope]}]
        descriptors.append(
            mcp_types.Tool(
                name=ISSUE56_DIAGNOSTIC_TOOL_NAME,
                title="Query the Issue 56 diagnostic effective graph view",
                description=(
                    "Diagnostic-only Issue #56 effective-graph query; "
                    "not a production-store or methodology-readiness claim."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {"query_text": {"type": "string"}},
                    "required": ["query_text"],
                    "additionalProperties": False,
                },
                outputSchema={
                    "type": "object",
                    "required": ["result_type", "status", "data", "warnings"],
                    "properties": {
                        "result_type": {"const": "effective_graph_query"},
                        "status": {"type": "string"},
                        "data": {"type": "object"},
                        "warnings": {"type": "array"},
                    },
                    "additionalProperties": True,
                },
                annotations=mcp_types.ToolAnnotations(
                    title="Query the Issue 56 diagnostic effective graph view",
                    readOnlyHint=True,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=False,
                ),
                securitySchemes=schemes,
                _meta={"securitySchemes": schemes},
            )
        )
        return descriptors


@dataclass(frozen=True)
class Issue56DiagnosticComposition:
    application: ConnectedMcpApplication
    bridge: Issue56DiagnosticOAuthBridge
    state: Issue56DiagnosticState
    session: AuthorizedSemanticMailSession = field(repr=False)
    effective_graph_view: EffectiveGraphView = field(repr=False)
    diagnostic_mode_id: str
    source_fixture_mode: str
    sealed_source_asset_status: str
    allowed_relation_types: tuple[str, ...]
    source_asset_fingerprint: str | None = None
    loader_contract_fingerprint: str | None = None
    observation_inventory_fingerprint: str | None = None
    permission_lineage_fingerprint: str | None = None
    effective_graph_view_fingerprint: str | None = None
    graph_revision_fingerprint: str | None = None
    source_loader_binding_fingerprint: str | None = None
    source_binding_fingerprint: str | None = None
    source_observation_count: int = 0
    lineage_crosswalk_precompute: Issue56LineageCrosswalkPrecomputeEvidence | None = None
    relation_projection_base_precompute: Issue56RelationProjectionBasePrecomputeEvidence | None = (
        None
    )
    prompt_selection: Issue56SourceBackedPromptSelectionEvidence | None = None
    relation_projection_cache_role: str = "default"

    @property
    def bearer_token(self) -> str:
        return _SYNTHETIC_BEARER


def build_issue56_sealed_source_diagnostic_input(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    allowed_relation_types: Sequence[str],
    source_asset_fingerprint: str,
    loader_contract_fingerprint: str,
    graph_revision_fingerprint: str,
    source_loader_binding_fingerprint: str,
    lineage_crosswalk_precompute: Mapping[str, Any],
    relation_projection_base_precompute: Mapping[str, Any],
    private_prompt: str | None = None,
    prompt_selection: Mapping[str, Any] | None = None,
    diagnostic_mode_id: str = ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
) -> Issue56SealedSourceDiagnosticInput:
    """Bind a loader-validated sealed asset to one authorized query projection."""

    relations = tuple(sorted(set(allowed_relation_types)))
    observation_inventory_fingerprint = _observation_inventory_fingerprint(session)
    permission_lineage_fingerprint = _permission_lineage_fingerprint(
        session=session,
        effective_graph_view=effective_graph_view,
    )
    effective_graph_view_fingerprint = sha256_json(effective_graph_view.to_dict())
    precompute_evidence = _validated_lineage_crosswalk_precompute_evidence(
        lineage_crosswalk_precompute,
        expected_index_fingerprint=session.index.index_fingerprint,
        expected_graph_revision_fingerprint=graph_revision_fingerprint,
        expected_authorized_evidence_count=len(session.authorized_observations),
    )
    relation_base_precompute_evidence = _validated_relation_projection_base_precompute_evidence(
        relation_projection_base_precompute,
        session=session,
        effective_graph_view=effective_graph_view,
        expected_graph_revision_fingerprint=graph_revision_fingerprint,
    )
    prompt_selection_evidence = _validated_source_backed_prompt_selection_evidence(
        prompt_selection,
        private_prompt=private_prompt,
        expected_source_loader_binding_fingerprint=source_loader_binding_fingerprint,
        expected_index_fingerprint=session.index.index_fingerprint,
        expected_graph_revision_fingerprint=graph_revision_fingerprint,
        expected_session=session,
        expected_allowed_relation_types=relations,
        required=(diagnostic_mode_id in _REAL_PROMPT_DIAGNOSTIC_MODE_IDS),
    )
    source_binding_fingerprint = _sealed_source_binding_fingerprint(
        session=session,
        source_asset_fingerprint=source_asset_fingerprint,
        loader_contract_fingerprint=loader_contract_fingerprint,
        observation_inventory_fingerprint=observation_inventory_fingerprint,
        permission_lineage_fingerprint=permission_lineage_fingerprint,
        effective_graph_view_fingerprint=effective_graph_view_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        source_loader_binding_fingerprint=source_loader_binding_fingerprint,
        lineage_crosswalk_precompute_binding_fingerprint=(
            precompute_evidence.evidence_binding_fingerprint
        ),
        relation_projection_base_precompute_binding_fingerprint=(
            relation_base_precompute_evidence.evidence_binding_fingerprint
        ),
        prompt_selection_proof_fingerprint=(
            prompt_selection_evidence.selection_proof_fingerprint
            if prompt_selection_evidence is not None
            else None
        ),
        allowed_relation_types=relations,
        diagnostic_mode_id=diagnostic_mode_id,
    )
    source = Issue56SealedSourceDiagnosticInput(
        session=session,
        effective_graph_view=effective_graph_view,
        allowed_relation_types=relations,
        source_asset_fingerprint=source_asset_fingerprint,
        loader_contract_fingerprint=loader_contract_fingerprint,
        observation_inventory_fingerprint=observation_inventory_fingerprint,
        permission_lineage_fingerprint=permission_lineage_fingerprint,
        effective_graph_view_fingerprint=effective_graph_view_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        source_loader_binding_fingerprint=source_loader_binding_fingerprint,
        source_binding_fingerprint=source_binding_fingerprint,
        observation_count=len(session.authorized_observations),
        lineage_crosswalk_precompute=precompute_evidence,
        relation_projection_base_precompute=relation_base_precompute_evidence,
        private_prompt=private_prompt,
        prompt_selection=prompt_selection_evidence,
        diagnostic_mode_id=diagnostic_mode_id,
    )
    _validate_sealed_source_diagnostic_input(source)
    return source


def _validate_sealed_source_diagnostic_input(
    source: Issue56SealedSourceDiagnosticInput,
) -> None:
    if not isinstance(source, Issue56SealedSourceDiagnosticInput):
        raise ContractValidationError("sealed-source diagnostic loader result is invalid")
    session = source.session
    view = source.effective_graph_view
    if source.diagnostic_mode_id not in {
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }:
        raise ContractValidationError("sealed-source diagnostic mode binding mismatch")
    real_prompt_mode = source.diagnostic_mode_id in _REAL_PROMPT_DIAGNOSTIC_MODE_IDS
    if real_prompt_mode:
        expected_prompt_selection = _validated_source_backed_prompt_selection_evidence(
            (
                source.prompt_selection.to_safe_dict()
                if source.prompt_selection is not None
                else None
            ),
            private_prompt=source.private_prompt,
            expected_source_loader_binding_fingerprint=(source.source_loader_binding_fingerprint),
            expected_index_fingerprint=source.session.index.index_fingerprint,
            expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
            expected_session=source.session,
            expected_allowed_relation_types=source.allowed_relation_types,
            required=True,
        )
        if expected_prompt_selection != source.prompt_selection:
            raise ContractValidationError("sealed-source prompt selection evidence drift")
    elif source.private_prompt is not None or source.prompt_selection is not None:
        raise ContractValidationError(
            "legacy sealed-source mode cannot carry a private prompt selection"
        )
    if not isinstance(session, AuthorizedSemanticMailSession):
        raise ContractValidationError("sealed-source diagnostic session is invalid")
    if not isinstance(view, EffectiveGraphView):
        raise ContractValidationError("sealed-source effective graph view is invalid")
    if (
        session.requester_user_id != ISSUE56_DIAGNOSTIC_USER_ID
        or session.workspace_id != ISSUE56_DIAGNOSTIC_WORKSPACE_ID
        or view.requester_user_id != ISSUE56_DIAGNOSTIC_USER_ID
    ):
        raise ContractValidationError("sealed-source diagnostic identity binding mismatch")
    if (
        session.authorized_source is None
        or session.authorized_source.workspace_id != ISSUE56_DIAGNOSTIC_WORKSPACE_ID
        or session.selected_source_scope_ids != session.authorized_source_scope_ids
        or session.index.denied_bundle_count != 0
    ):
        raise ContractValidationError("sealed-source diagnostic authorization scope mismatch")
    if source.observation_count <= 0 or source.observation_count != len(
        session.authorized_observations
    ):
        raise ContractValidationError("sealed-source observation count mismatch")
    observation_ids = {
        observation.observation_id for observation in session.authorized_observations
    }
    if len(observation_ids) != source.observation_count:
        raise ContractValidationError("sealed-source observation inventory is not unique")
    actual_observation_hashes = tuple(
        sorted(
            (
                observation.observation_id,
                sha256_json(observation.to_dict()),
            )
            for observation in session.authorized_observations
        )
    )
    if session.authorized_observation_hashes != actual_observation_hashes:
        raise ContractValidationError("sealed-source authorized observation seal mismatch")
    permission_scope_fingerprint_by_observation_id: dict[str, str] = {}
    for observation in session.authorized_observations:
        permission_scope = _validated_restricted_source_permission_scope(
            observation.permission_scope,
            label="sealed-source observation",
            workspace_id=session.workspace_id,
            authorized_source_scope_ids=session.authorized_source_scope_ids,
            source_record_bound=bool(observation.asset_id or observation.evidence_snapshot_id),
        )
        permission_scope_fingerprint_by_observation_id[observation.observation_id] = sha256_json(
            permission_scope
        )
        _assert_no_legacy_identity_fields(observation.to_dict())
    if not source.allowed_relation_types or source.allowed_relation_types != tuple(
        sorted(set(source.allowed_relation_types))
    ):
        raise ContractValidationError("sealed-source allowed relation set is invalid")
    graph_relation_types = {edge.relation_type for edge in view.visible_edges}
    if not set(source.allowed_relation_types).issubset(graph_relation_types):
        raise ContractValidationError("sealed-source relation binding mismatch")
    for node in view.visible_nodes:
        node_permission_scope = _validated_restricted_source_permission_scope(
            node.permission_scope,
            label="sealed-source graph node",
            workspace_id=session.workspace_id,
            authorized_source_scope_ids=session.authorized_source_scope_ids,
            source_record_bound=True,
        )
        _validate_graph_source_observation_binding(
            node.properties,
            item_permission_scope=node_permission_scope,
            permission_scope_fingerprint_by_observation_id=(
                permission_scope_fingerprint_by_observation_id
            ),
            label="sealed-source graph node",
        )
    for edge in view.visible_edges:
        edge_permission_scope = _validated_restricted_source_permission_scope(
            edge.permission_scope,
            label="sealed-source graph edge",
            workspace_id=session.workspace_id,
            authorized_source_scope_ids=session.authorized_source_scope_ids,
            source_record_bound=True,
        )
        _validate_graph_source_observation_binding(
            edge.properties,
            item_permission_scope=edge_permission_scope,
            permission_scope_fingerprint_by_observation_id=(
                permission_scope_fingerprint_by_observation_id
            ),
            label="sealed-source graph edge",
        )
    _assert_no_legacy_identity_fields(view.to_dict())
    _require_sha256(source.source_asset_fingerprint, "sealed source asset fingerprint")
    _require_sha256(
        source.loader_contract_fingerprint,
        "sealed source loader contract fingerprint",
    )
    _require_sha256(
        source.graph_revision_fingerprint,
        "sealed source graph revision fingerprint",
    )
    _require_sha256(
        source.source_loader_binding_fingerprint,
        "sealed source loader binding fingerprint",
    )
    if source.observation_inventory_fingerprint != _observation_inventory_fingerprint(session):
        raise ContractValidationError("sealed-source observation inventory fingerprint mismatch")
    if source.permission_lineage_fingerprint != _permission_lineage_fingerprint(
        session=session,
        effective_graph_view=view,
    ):
        raise ContractValidationError("sealed-source permission lineage fingerprint mismatch")
    if source.effective_graph_view_fingerprint != sha256_json(view.to_dict()):
        raise ContractValidationError("sealed-source effective graph fingerprint mismatch")
    expected_precompute = _validated_lineage_crosswalk_precompute_evidence(
        source.lineage_crosswalk_precompute.to_safe_dict(),
        expected_index_fingerprint=session.index.index_fingerprint,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
        expected_authorized_evidence_count=source.observation_count,
    )
    if expected_precompute != source.lineage_crosswalk_precompute:
        raise ContractValidationError("sealed-source lineage precompute evidence drift")
    expected_relation_base_precompute = _validated_relation_projection_base_precompute_evidence(
        source.relation_projection_base_precompute.to_safe_dict(),
        session=session,
        effective_graph_view=view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
    )
    if expected_relation_base_precompute != source.relation_projection_base_precompute:
        raise ContractValidationError(
            "sealed-source relation projection base precompute evidence drift"
        )
    expected_binding = _sealed_source_binding_fingerprint(
        session=session,
        source_asset_fingerprint=source.source_asset_fingerprint,
        loader_contract_fingerprint=source.loader_contract_fingerprint,
        observation_inventory_fingerprint=source.observation_inventory_fingerprint,
        permission_lineage_fingerprint=source.permission_lineage_fingerprint,
        effective_graph_view_fingerprint=source.effective_graph_view_fingerprint,
        graph_revision_fingerprint=source.graph_revision_fingerprint,
        source_loader_binding_fingerprint=source.source_loader_binding_fingerprint,
        lineage_crosswalk_precompute_binding_fingerprint=(
            source.lineage_crosswalk_precompute.evidence_binding_fingerprint
        ),
        relation_projection_base_precompute_binding_fingerprint=(
            source.relation_projection_base_precompute.evidence_binding_fingerprint
        ),
        prompt_selection_proof_fingerprint=(
            source.prompt_selection.selection_proof_fingerprint
            if source.prompt_selection is not None
            else None
        ),
        allowed_relation_types=source.allowed_relation_types,
        diagnostic_mode_id=source.diagnostic_mode_id,
    )
    if source.source_binding_fingerprint != expected_binding:
        raise ContractValidationError("sealed-source diagnostic binding fingerprint mismatch")


def _observation_inventory_fingerprint(
    session: AuthorizedSemanticMailSession,
) -> str:
    return sha256_json(
        [
            {
                "observation_id": observation.observation_id,
                "observation_hash": sha256_json(observation.to_dict()),
            }
            for observation in sorted(
                session.authorized_observations,
                key=lambda item: item.observation_id,
            )
        ]
    )


def _sealed_source_binding_fingerprint(
    *,
    session: AuthorizedSemanticMailSession,
    source_asset_fingerprint: str,
    loader_contract_fingerprint: str,
    observation_inventory_fingerprint: str,
    permission_lineage_fingerprint: str,
    effective_graph_view_fingerprint: str,
    graph_revision_fingerprint: str,
    source_loader_binding_fingerprint: str,
    lineage_crosswalk_precompute_binding_fingerprint: str,
    relation_projection_base_precompute_binding_fingerprint: str,
    prompt_selection_proof_fingerprint: str | None,
    allowed_relation_types: Sequence[str],
    diagnostic_mode_id: str,
) -> str:
    return sha256_json(
        {
            "schema_version": 4,
            "diagnostic_mode_id": diagnostic_mode_id,
            "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
            "workspace_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
            "approver_user_id": ISSUE56_DIAGNOSTIC_USER_ID,
            "source_asset_fingerprint": source_asset_fingerprint,
            "loader_contract_fingerprint": loader_contract_fingerprint,
            "observation_inventory_fingerprint": observation_inventory_fingerprint,
            "permission_lineage_fingerprint": permission_lineage_fingerprint,
            "effective_graph_view_fingerprint": effective_graph_view_fingerprint,
            "graph_revision_fingerprint": graph_revision_fingerprint,
            "source_loader_binding_fingerprint": source_loader_binding_fingerprint,
            "lineage_crosswalk_precompute_binding_fingerprint": (
                lineage_crosswalk_precompute_binding_fingerprint
            ),
            "relation_projection_base_precompute_binding_fingerprint": (
                relation_projection_base_precompute_binding_fingerprint
            ),
            "prompt_selection_proof_fingerprint": (prompt_selection_proof_fingerprint),
            "session_binding_fingerprint": _semantic_session_binding_fingerprint(session),
            "allowed_relation_types": list(allowed_relation_types),
        }
    )


def _validated_source_backed_prompt_selection_evidence(
    raw: Mapping[str, Any] | None,
    *,
    private_prompt: str | None,
    expected_source_loader_binding_fingerprint: str,
    expected_index_fingerprint: str,
    expected_graph_revision_fingerprint: str,
    expected_session: AuthorizedSemanticMailSession | None = None,
    expected_allowed_relation_types: Sequence[str] = (),
    required: bool,
) -> Issue56SourceBackedPromptSelectionEvidence | None:
    if not required:
        if raw is not None or private_prompt is not None:
            raise ContractValidationError(
                "source-backed prompt selection is not allowed for this mode"
            )
        return None
    if not isinstance(private_prompt, str) or not private_prompt.strip():
        raise ContractValidationError("source-backed private prompt is unavailable")
    if not isinstance(raw, Mapping):
        raise ContractValidationError("source-backed prompt selection proof is unavailable")
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "prompt_hash",
        "source_loader_binding_fingerprint",
        "permission_fingerprint",
        "owner_selection_proof",
        "selection_proof_fingerprint",
        "counts",
    }
    if set(raw) != expected_keys:
        raise ContractValidationError("source-backed prompt selection proof schema mismatch")
    if (
        raw.get("artifact_id") != "formowl_issue56_real_prompt_gateway_selection_binding_v1"
        or raw.get("schema_version") != 1
        or raw.get("status") != "passed"
    ):
        raise ContractValidationError("source-backed prompt selection proof contract mismatch")
    owner_proof = raw.get("owner_selection_proof")
    if not isinstance(owner_proof, Mapping):
        raise ContractValidationError("source-backed owner prompt selection proof is invalid")
    owner_expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "claim_boundary",
        "selection_algorithm_id",
        "prompt_template_fingerprint",
        "selected_identifier_count",
        "selected_term_hashes",
        "selected_node_hashes",
        "selected_edge_hashes",
        "selected_observation_hashes",
        "identifier_support",
        "path_hop_count",
        "path_node_count",
        "path_edge_count",
        "path_observation_count",
        "allowed_relation_type_hashes",
        "max_hops",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "source_access_fingerprint",
        "source_session_binding_fingerprint",
        "candidate_inventory_fingerprint",
        "identity_scope_mode_fingerprint",
        "identity_scope_fingerprint",
        "workspace_scope_fingerprint",
        "requester_fingerprint",
        "synthetic_fallback_used",
        "query_executed",
        "selection_proof_fingerprint",
    }
    if (
        set(owner_proof) != owner_expected_keys
        or owner_proof.get("artifact_id")
        != "formowl_issue56_source_backed_connected_identifier_prompt_selection_v1"
        or owner_proof.get("schema_version") != 1
        or owner_proof.get("status") != "selected"
        or owner_proof.get("claim_boundary") != "diagnostic_prompt_selection_only_no_query_executed"
        or owner_proof.get("selection_algorithm_id")
        != "issue56_source_backed_connected_identifier_prompt_selection_v1"
        or owner_proof.get("synthetic_fallback_used") is not False
        or owner_proof.get("query_executed") is not False
    ):
        raise ContractValidationError(
            "source-backed owner prompt selection proof contract mismatch"
        )
    selected_term_hashes = owner_proof.get("selected_term_hashes")
    selected_node_hashes = owner_proof.get("selected_node_hashes")
    selected_edge_hashes = owner_proof.get("selected_edge_hashes")
    selected_observation_hashes = owner_proof.get("selected_observation_hashes")
    identifier_support = owner_proof.get("identifier_support")
    integer_fields = (
        "selected_identifier_count",
        "path_hop_count",
        "path_node_count",
        "path_edge_count",
        "path_observation_count",
        "max_hops",
    )
    if (
        any(
            type(owner_proof.get(field_name)) is not int or owner_proof[field_name] < 0
            for field_name in integer_fields
        )
        or owner_proof["selected_identifier_count"] != 2
        or owner_proof["path_hop_count"] <= 0
        or owner_proof["path_hop_count"] > owner_proof["max_hops"]
        or owner_proof["max_hops"] > 2
        or owner_proof["path_edge_count"] != owner_proof["path_hop_count"]
        or owner_proof["path_node_count"] != owner_proof["path_edge_count"] + 1
        or owner_proof["path_observation_count"] <= 0
        or not isinstance(selected_term_hashes, list)
        or len(selected_term_hashes) != 2
        or len(set(selected_term_hashes)) != 2
        or not isinstance(selected_node_hashes, list)
        or len(selected_node_hashes) != owner_proof["path_node_count"]
        or not isinstance(selected_edge_hashes, list)
        or len(selected_edge_hashes) != owner_proof["path_edge_count"]
        or not isinstance(selected_observation_hashes, list)
        or len(selected_observation_hashes) != owner_proof["path_observation_count"]
        or not isinstance(identifier_support, list)
        or len(identifier_support) != 2
    ):
        raise ContractValidationError(
            "source-backed owner prompt selection proof counts are invalid"
        )
    summary_counts = raw.get("counts")
    expected_summary_counts = {
        "lexical_anchor_count": len(selected_term_hashes),
        "selected_identifier_count": int(owner_proof["selected_identifier_count"]),
        "authorized_connected_graph_path_count": 1,
        "supporting_observation_count": int(owner_proof["path_observation_count"]),
    }
    if summary_counts != expected_summary_counts:
        raise ContractValidationError("source-backed prompt selection summary count mismatch")
    hash_list_fields = (
        selected_term_hashes,
        selected_node_hashes,
        selected_edge_hashes,
        selected_observation_hashes,
        owner_proof.get("allowed_relation_type_hashes"),
    )
    if any(
        not isinstance(values, list) or any(not isinstance(value, str) for value in values)
        for values in hash_list_fields
    ):
        raise ContractValidationError("source-backed owner prompt selection hashes are invalid")
    for values in hash_list_fields:
        for value in values:
            _require_sha256(value, "owner prompt selection hash")
    validated_support_rows: list[Mapping[str, Any]] = []
    for row in identifier_support:
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {
                "term_hash",
                "node_hash",
                "support_observation_hashes",
            }
            or not isinstance(row.get("support_observation_hashes"), list)
            or not row["support_observation_hashes"]
        ):
            raise ContractValidationError("source-backed owner identifier support is invalid")
        _require_sha256(str(row.get("term_hash", "")), "support term hash")
        _require_sha256(str(row.get("node_hash", "")), "support node hash")
        for observation_hash in row["support_observation_hashes"]:
            _require_sha256(str(observation_hash), "support observation hash")
        validated_support_rows.append(row)
    if {row["term_hash"] for row in validated_support_rows} != set(selected_term_hashes) or any(
        row["node_hash"] not in selected_node_hashes
        or not set(row["support_observation_hashes"]).issubset(selected_observation_hashes)
        for row in validated_support_rows
    ):
        raise ContractValidationError("source-backed owner identifier support binding mismatch")
    for field_name in (
        "prompt_hash",
        "source_loader_binding_fingerprint",
        "permission_fingerprint",
        "selection_proof_fingerprint",
    ):
        _require_sha256(str(raw.get(field_name, "")), field_name)
    for field_name in (
        "prompt_template_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "source_access_fingerprint",
        "source_session_binding_fingerprint",
        "candidate_inventory_fingerprint",
        "identity_scope_mode_fingerprint",
        "identity_scope_fingerprint",
        "workspace_scope_fingerprint",
        "requester_fingerprint",
        "selection_proof_fingerprint",
    ):
        _require_sha256(str(owner_proof.get(field_name, "")), field_name)
    owner_without_self = dict(owner_proof)
    owner_selection_proof_fingerprint = owner_without_self.pop("selection_proof_fingerprint")
    if sha256_json(owner_without_self) != owner_selection_proof_fingerprint:
        raise ContractValidationError("source-backed owner prompt selection proof seal mismatch")
    if (
        raw["prompt_hash"] != sha256_json(private_prompt)
        or raw["source_loader_binding_fingerprint"] != expected_source_loader_binding_fingerprint
        or owner_proof["index_fingerprint"] != expected_index_fingerprint
        or owner_proof["graph_revision_fingerprint"] != expected_graph_revision_fingerprint
    ):
        raise ContractValidationError("source-backed prompt selection proof binding mismatch")
    if expected_session is not None:
        expected_source_access_fingerprint = (
            expected_session.authorized_source.authorization_fingerprint
            if expected_session.authorized_source is not None
            else None
        )
        if (
            owner_proof["workspace_scope_fingerprint"] != sha256_json(expected_session.workspace_id)
            or owner_proof["requester_fingerprint"]
            != sha256_json(expected_session.requester_user_id)
            or owner_proof["identity_scope_mode_fingerprint"]
            != sha256_json(ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE)
            or expected_source_access_fingerprint is None
            or owner_proof["source_access_fingerprint"] != expected_source_access_fingerprint
            or owner_proof["allowed_relation_type_hashes"]
            != [sha256_json(item) for item in sorted(set(expected_allowed_relation_types))]
        ):
            raise ContractValidationError(
                "source-backed owner prompt selection authorization mismatch"
            )
    proof_payload = dict(raw)
    supplied_fingerprint = proof_payload.pop("selection_proof_fingerprint")
    if sha256_json(proof_payload) != supplied_fingerprint:
        raise ContractValidationError("source-backed prompt selection proof seal mismatch")
    evidence = Issue56SourceBackedPromptSelectionEvidence(
        status=str(raw["status"]),
        prompt_hash=str(raw["prompt_hash"]),
        source_loader_binding_fingerprint=str(raw["source_loader_binding_fingerprint"]),
        permission_fingerprint=str(raw["permission_fingerprint"]),
        index_fingerprint=str(owner_proof["index_fingerprint"]),
        graph_revision_fingerprint=str(owner_proof["graph_revision_fingerprint"]),
        lexical_anchor_count=expected_summary_counts["lexical_anchor_count"],
        selected_identifier_count=expected_summary_counts["selected_identifier_count"],
        authorized_connected_graph_path_count=expected_summary_counts[
            "authorized_connected_graph_path_count"
        ],
        supporting_observation_count=expected_summary_counts["supporting_observation_count"],
        owner_selection_proof_fingerprint=str(owner_selection_proof_fingerprint),
        owner_selection_proof=MappingProxyType(dict(owner_proof)),
        selection_proof_fingerprint=str(supplied_fingerprint),
    )
    _assert_no_legacy_identity_fields(evidence.to_safe_dict())
    assert_no_public_raw_references(
        evidence.to_safe_dict(),
        "issue56_source_backed_prompt_selection",
    )
    return evidence


def _validated_lineage_crosswalk_precompute_evidence(
    raw: Mapping[str, Any],
    *,
    expected_index_fingerprint: str,
    expected_graph_revision_fingerprint: str,
    expected_authorized_evidence_count: int,
) -> Issue56LineageCrosswalkPrecomputeEvidence:
    if not isinstance(raw, Mapping):
        raise ContractValidationError("sealed-source lineage precompute evidence is invalid")
    expected_keys = {
        "status",
        "cache_status",
        "helper_invocation_count",
        "elapsed_ms",
        "crosswalk_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "cache_key_fingerprint",
        "counts",
    }
    optional_keys = {"artifact_id", "schema_version", "evidence_binding_fingerprint"}
    if not set(raw).issubset(expected_keys | optional_keys) or not expected_keys.issubset(raw):
        raise ContractValidationError("sealed-source lineage precompute evidence schema mismatch")
    if (
        raw.get("artifact_id") != "formowl_issue56_lineage_crosswalk_precompute_safe_v1"
        or raw.get("schema_version") != 1
    ):
        raise ContractValidationError("sealed-source lineage precompute contract mismatch")
    counts = raw.get("counts")
    expected_count_keys = {
        "authorized_evidence_count",
        "indexed_evidence_count",
        "occurrence_bound_evidence_count",
        "graph_node_bound_evidence_count",
        "graph_edge_bound_evidence_count",
    }
    if not isinstance(counts, Mapping) or set(counts) != expected_count_keys:
        raise ContractValidationError("sealed-source lineage precompute counts are invalid")
    if (
        raw.get("status") != "passed"
        or raw.get("cache_status") != "primed"
        or raw.get("helper_invocation_count") != 1
        or isinstance(raw.get("elapsed_ms"), bool)
        or not isinstance(raw.get("elapsed_ms"), (int, float))
        or raw["elapsed_ms"] < 0
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        raise ContractValidationError("sealed-source lineage precompute status is invalid")
    for field_name in (
        "crosswalk_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "cache_key_fingerprint",
    ):
        _require_sha256(str(raw.get(field_name, "")), f"sealed source {field_name}")
    if (
        raw["index_fingerprint"] != expected_index_fingerprint
        or raw["graph_revision_fingerprint"] != expected_graph_revision_fingerprint
        or counts["authorized_evidence_count"] != expected_authorized_evidence_count
    ):
        raise ContractValidationError("sealed-source lineage precompute binding mismatch")
    evidence_payload = {
        "schema_version": 1,
        "status": raw["status"],
        "cache_status": raw["cache_status"],
        "helper_invocation_count": raw["helper_invocation_count"],
        "elapsed_ms": round(float(raw["elapsed_ms"]), 6),
        "crosswalk_fingerprint": raw["crosswalk_fingerprint"],
        "index_fingerprint": raw["index_fingerprint"],
        "graph_revision_fingerprint": raw["graph_revision_fingerprint"],
        "cache_key_fingerprint": raw["cache_key_fingerprint"],
        "counts": {key: counts[key] for key in sorted(expected_count_keys)},
    }
    evidence_binding_fingerprint = sha256_json(evidence_payload)
    supplied_binding = raw.get("evidence_binding_fingerprint")
    if supplied_binding is not None and supplied_binding != evidence_binding_fingerprint:
        raise ContractValidationError("sealed-source lineage precompute evidence seal mismatch")
    return Issue56LineageCrosswalkPrecomputeEvidence(
        status=str(raw["status"]),
        cache_status=str(raw["cache_status"]),
        helper_invocation_count=int(raw["helper_invocation_count"]),
        elapsed_ms=evidence_payload["elapsed_ms"],
        crosswalk_fingerprint=str(raw["crosswalk_fingerprint"]),
        index_fingerprint=str(raw["index_fingerprint"]),
        graph_revision_fingerprint=str(raw["graph_revision_fingerprint"]),
        cache_key_fingerprint=str(raw["cache_key_fingerprint"]),
        authorized_evidence_count=int(counts["authorized_evidence_count"]),
        indexed_evidence_count=int(counts["indexed_evidence_count"]),
        occurrence_bound_evidence_count=int(counts["occurrence_bound_evidence_count"]),
        graph_node_bound_evidence_count=int(counts["graph_node_bound_evidence_count"]),
        graph_edge_bound_evidence_count=int(counts["graph_edge_bound_evidence_count"]),
        evidence_binding_fingerprint=evidence_binding_fingerprint,
    )


def _validated_relation_projection_base_precompute_evidence(
    raw: Mapping[str, Any],
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
    expected_graph_revision_fingerprint: str,
) -> Issue56RelationProjectionBasePrecomputeEvidence:
    if not isinstance(raw, Mapping):
        raise ContractValidationError(
            "sealed-source relation projection base precompute evidence is invalid"
        )
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "cache_status",
        "helper_invocation_count",
        "elapsed_ms",
        "cache_binding_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "precompute_fingerprint",
        "counts",
    }
    optional_keys = {"evidence_binding_fingerprint"}
    if not set(raw).issubset(expected_keys | optional_keys) or not expected_keys.issubset(raw):
        raise ContractValidationError(
            "sealed-source relation projection base precompute evidence schema mismatch"
        )
    if (
        raw.get("artifact_id") != "formowl_issue56_relation_projection_base_precompute_v1"
        or raw.get("schema_version") != 1
    ):
        raise ContractValidationError(
            "sealed-source relation projection base precompute contract mismatch"
        )
    counts = raw.get("counts")
    expected_count_keys = {
        "authorized_observation_count",
        "candidate_count",
        "projected_node_count",
        "observation_bound_node_group_count",
        "adjacency_node_count",
        "adjacency_transition_count",
        "authorized_index_vocabulary_hash_count",
        "authorized_graph_vocabulary_hash_count",
    }
    if not isinstance(counts, Mapping) or set(counts) != expected_count_keys:
        raise ContractValidationError(
            "sealed-source relation projection base precompute counts are invalid"
        )
    if (
        raw.get("status") != "passed"
        or raw.get("cache_status") != "primed"
        or raw.get("helper_invocation_count") != 1
        or isinstance(raw.get("elapsed_ms"), bool)
        or not isinstance(raw.get("elapsed_ms"), (int, float))
        or raw["elapsed_ms"] < 0
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        raise ContractValidationError(
            "sealed-source relation projection base precompute status is invalid"
        )
    fingerprint_fields = (
        "cache_binding_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "precompute_fingerprint",
    )
    for field_name in fingerprint_fields:
        _require_sha256(str(raw.get(field_name, "")), f"sealed source {field_name}")
    candidates_by_hash = {
        candidate.source_observation_hash: candidate for candidate in session.index.candidates
    }
    expected_authorized_observation_set_fingerprint = sha256_json(
        sorted(session.authorized_observation_hashes)
    )
    expected_candidate_set_fingerprint = sha256_json(
        [
            [
                observation_hash,
                candidate.index_binding_hash,
                candidate.message_occurrence_hash,
            ]
            for observation_hash, candidate in sorted(candidates_by_hash.items())
        ]
    )
    authorized_observation_ids = dict(session.authorized_observation_hashes)
    observation_bound_node_group_count = len(
        {
            source_observation_id
            for node in effective_graph_view.visible_nodes
            for source_observation_id in node.properties.get(
                "source_observation_ids",
                (),
            )
            if isinstance(source_observation_id, str)
            and source_observation_id in authorized_observation_ids
        }
    )
    adjacency_node_count = len(
        {
            node_id
            for edge in effective_graph_view.visible_edges
            for node_id in (edge.source_node_id, edge.target_node_id)
        }
    )
    expected_precompute_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_issue56_relation_projection_base_precompute_v1",
            "cache_binding_fingerprint": raw["cache_binding_fingerprint"],
            "graph_revision_fingerprint": raw["graph_revision_fingerprint"],
            "index_fingerprint": raw["index_fingerprint"],
            "tokenizer_profile_fingerprint": raw["candidate_admission_profile_fingerprint"],
            "authorized_observation_set_fingerprint": raw["authorized_observation_set_fingerprint"],
            "candidate_set_fingerprint": raw["candidate_set_fingerprint"],
            **{key: counts[key] for key in expected_count_keys},
        }
    )
    if (
        raw["index_fingerprint"] != session.index.index_fingerprint
        or raw["graph_revision_fingerprint"] != expected_graph_revision_fingerprint
        or raw["candidate_admission_profile_fingerprint"] != session.index.profile_fingerprint
        or raw["authorized_observation_set_fingerprint"]
        != expected_authorized_observation_set_fingerprint
        or raw["candidate_set_fingerprint"] != expected_candidate_set_fingerprint
        or raw["precompute_fingerprint"] != expected_precompute_fingerprint
        or counts["authorized_observation_count"] != len(session.authorized_observations)
        or counts["candidate_count"] != len(candidates_by_hash)
        or counts["projected_node_count"] != len(effective_graph_view.visible_nodes)
        or counts["observation_bound_node_group_count"] != observation_bound_node_group_count
        or counts["adjacency_node_count"] != adjacency_node_count
        or counts["adjacency_transition_count"] != 2 * len(effective_graph_view.visible_edges)
    ):
        raise ContractValidationError(
            "sealed-source relation projection base precompute binding mismatch"
        )
    evidence_payload = {
        "schema_version": 1,
        "status": raw["status"],
        "cache_status": raw["cache_status"],
        "helper_invocation_count": raw["helper_invocation_count"],
        "elapsed_ms": round(float(raw["elapsed_ms"]), 6),
        **{field_name: raw[field_name] for field_name in fingerprint_fields},
        "counts": {key: counts[key] for key in sorted(expected_count_keys)},
    }
    evidence_binding_fingerprint = sha256_json(evidence_payload)
    supplied_binding = raw.get("evidence_binding_fingerprint")
    if supplied_binding is not None and supplied_binding != evidence_binding_fingerprint:
        raise ContractValidationError(
            "sealed-source relation projection base precompute evidence seal mismatch"
        )
    return Issue56RelationProjectionBasePrecomputeEvidence(
        status=str(raw["status"]),
        cache_status=str(raw["cache_status"]),
        helper_invocation_count=int(raw["helper_invocation_count"]),
        elapsed_ms=evidence_payload["elapsed_ms"],
        cache_binding_fingerprint=str(raw["cache_binding_fingerprint"]),
        index_fingerprint=str(raw["index_fingerprint"]),
        graph_revision_fingerprint=str(raw["graph_revision_fingerprint"]),
        candidate_admission_profile_fingerprint=str(raw["candidate_admission_profile_fingerprint"]),
        authorized_observation_set_fingerprint=str(raw["authorized_observation_set_fingerprint"]),
        candidate_set_fingerprint=str(raw["candidate_set_fingerprint"]),
        authorized_observation_count=int(counts["authorized_observation_count"]),
        candidate_count=int(counts["candidate_count"]),
        projected_node_count=int(counts["projected_node_count"]),
        observation_bound_node_group_count=int(counts["observation_bound_node_group_count"]),
        adjacency_node_count=int(counts["adjacency_node_count"]),
        adjacency_transition_count=int(counts["adjacency_transition_count"]),
        authorized_index_vocabulary_hash_count=int(
            counts["authorized_index_vocabulary_hash_count"]
        ),
        authorized_graph_vocabulary_hash_count=int(
            counts["authorized_graph_vocabulary_hash_count"]
        ),
        precompute_fingerprint=str(raw["precompute_fingerprint"]),
        evidence_binding_fingerprint=evidence_binding_fingerprint,
    )


def _semantic_session_binding_fingerprint(
    session: AuthorizedSemanticMailSession,
) -> str:
    return sha256_json(
        {
            "requester_user_id": session.requester_user_id,
            "workspace_id": session.workspace_id,
            "selected_source_scope_ids": list(session.selected_source_scope_ids),
            "authorized_source_scope_ids": list(session.authorized_source_scope_ids),
            "authorized_observation_hashes": [
                list(item) for item in session.authorized_observation_hashes
            ],
            "authorized_source_fingerprint": (
                session.authorized_source.authorization_fingerprint
                if session.authorized_source is not None
                else None
            ),
            "index_fingerprint": session.index.index_fingerprint,
            "runtime_method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
        }
    )


def _permission_lineage_fingerprint(
    *,
    session: AuthorizedSemanticMailSession,
    effective_graph_view: EffectiveGraphView,
) -> str:
    return sha256_json(
        {
            "schema_version": 1,
            "observation_permission_bindings": [
                {
                    "observation_hash": sha256_json(observation.to_dict()),
                    "permission_scope_fingerprint": sha256_json(dict(observation.permission_scope)),
                }
                for observation in sorted(
                    session.authorized_observations,
                    key=lambda item: item.observation_id,
                )
            ],
            "graph_node_permission_bindings": [
                {
                    "node_hash": sha256_json(node.to_dict()),
                    "permission_scope_fingerprint": sha256_json(dict(node.permission_scope)),
                    "source_observation_hashes": sorted(
                        sha256_json(source_id)
                        for source_id in node.properties.get(
                            "source_observation_ids",
                            (),
                        )
                        if isinstance(source_id, str)
                    ),
                }
                for node in sorted(
                    effective_graph_view.visible_nodes,
                    key=lambda item: item.node_id,
                )
            ],
            "graph_edge_permission_bindings": [
                {
                    "edge_hash": sha256_json(edge.to_dict()),
                    "permission_scope_fingerprint": sha256_json(dict(edge.permission_scope)),
                    "source_observation_hashes": sorted(
                        sha256_json(source_id)
                        for source_id in edge.properties.get(
                            "source_observation_ids",
                            (),
                        )
                        if isinstance(source_id, str)
                    ),
                }
                for edge in sorted(
                    effective_graph_view.visible_edges,
                    key=lambda item: item.edge_id,
                )
            ],
        }
    )


def _validate_graph_source_observation_binding(
    properties: Mapping[str, Any],
    *,
    item_permission_scope: Mapping[str, Any],
    permission_scope_fingerprint_by_observation_id: Mapping[str, str],
    label: str,
) -> None:
    source_ids = properties.get("source_observation_ids")
    if (
        not isinstance(source_ids, list)
        or not source_ids
        or len(set(source_ids)) != len(source_ids)
        or any(
            not isinstance(source_id, str)
            or source_id not in permission_scope_fingerprint_by_observation_id
            for source_id in source_ids
        )
    ):
        raise ContractValidationError(f"{label} source binding is invalid")
    item_scope_fingerprint = sha256_json(dict(item_permission_scope))
    if any(
        permission_scope_fingerprint_by_observation_id[source_id] != item_scope_fingerprint
        for source_id in source_ids
    ):
        raise ContractValidationError(f"{label} permission lineage mismatch")


def _validated_restricted_source_permission_scope(
    scope: Mapping[str, Any],
    *,
    label: str,
    workspace_id: str,
    authorized_source_scope_ids: Sequence[str],
    source_record_bound: bool,
) -> dict[str, Any]:
    if not isinstance(scope, Mapping):
        raise ContractValidationError(f"{label} permission scope mismatch")
    normalized = dict(scope)
    _assert_no_legacy_identity_fields(normalized)
    keys = frozenset(normalized)
    if (
        not _SEALED_SOURCE_PERMISSION_SCOPE_REQUIRED_FIELDS.issubset(keys)
        or not keys.issubset(
            _SEALED_SOURCE_PERMISSION_SCOPE_REQUIRED_FIELDS
            | _SEALED_SOURCE_PERMISSION_SCOPE_OPTIONAL_FIELDS
        )
        or normalized.get("visibility") != "restricted"
        or not source_record_bound
    ):
        raise ContractValidationError(f"{label} permission scope mismatch")
    scope_type = normalized.get("scope_type")
    scope_id = normalized.get("scope_id")
    if (
        not isinstance(scope_type, str)
        or scope_type not in _SUPPORTED_SEALED_SOURCE_PERMISSION_SCOPE_TYPES
        or not isinstance(scope_id, str)
        or not scope_id.strip()
    ):
        raise ContractValidationError(f"{label} permission scope type is unsupported")
    inherited_from = normalized.get("inherited_from")
    if inherited_from is not None and (
        not isinstance(inherited_from, str) or not inherited_from.strip()
    ):
        raise ContractValidationError(f"{label} permission scope mismatch")
    if scope_type == "workspace" and scope_id != workspace_id:
        raise ContractValidationError(f"{label} permission scope mismatch")
    if scope_type == "mail_import_session" and scope_id not in authorized_source_scope_ids:
        raise ContractValidationError(f"{label} permission scope mismatch")
    return normalized


def _require_sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ContractValidationError(f"{label} is invalid")


def _semantic_equivalence_projection(
    *,
    result: Any,
    answer: Any,
    permission_lineage_fingerprint: str | None,
    effective_graph_view_fingerprint: str | None,
    source_binding_fingerprint: str | None,
    relation_projection_base_precompute: (Issue56RelationProjectionBasePrecomputeEvidence | None),
) -> dict[str, Any]:
    """Return a timing-free, hash-only semantic comparison projection."""

    safe_result = result.to_safe_dict()
    lineage_payload = safe_result.get("lineage_audit")
    permission_payload = {
        "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        "permission_lineage_fingerprint": permission_lineage_fingerprint,
        "effective_graph_view_fingerprint": effective_graph_view_fingerprint,
        "source_binding_fingerprint": source_binding_fingerprint,
        "authorized_observation_set_fingerprint": (
            relation_projection_base_precompute.authorized_observation_set_fingerprint
            if relation_projection_base_precompute is not None
            else None
        ),
        "selected_bundle_count": result.selected_bundle_count,
        "authorized_bundle_count": result.authorized_bundle_count,
        "denied_bundle_count": result.denied_bundle_count,
    }
    projection = {
        "status": result.status,
        "answer_status": answer.status,
        "answer_hash": answer.answer_hash,
        "source_result_fingerprint": answer.source_result_fingerprint,
        "query_hash": result.query_hash,
        "plan_fingerprint": result.plan_fingerprint,
        "result_fingerprint": result.result_fingerprint,
        "semantic_payload_fingerprint": sha256_json(safe_result),
        "path_fingerprint": sha256_json(safe_result["graph_paths"]),
        "citation_fingerprint": sha256_json(safe_result["answer_citation_hashes"]),
        "score_fingerprint": sha256_json(safe_result["scores"]),
        "permission_fingerprint": sha256_json(permission_payload),
        "lineage_fingerprint": sha256_json(lineage_payload),
        "lineage_crosswalk_fingerprint": (
            lineage_payload.get("crosswalk_fingerprint")
            if isinstance(lineage_payload, Mapping)
            else None
        ),
        "runtime_method_fingerprint": result.runtime_method_fingerprint,
        "profile_fingerprint": result.profile_fingerprint,
        "index_fingerprint": result.index_fingerprint,
        "graph_revision_fingerprint": result.graph_revision_fingerprint,
        "execution_component_fingerprint": result.execution_component_fingerprint,
        "warnings_fingerprint": sha256_json(safe_result["warnings"]),
        "counts": {
            "graph_path_count": result.graph_path_count,
            "citation_count": len(result.answer_citation_hashes),
            "score_count": len(result.scores),
            "semantic_result_count": result.semantic_result_count,
            "selected_bundle_count": result.selected_bundle_count,
            "authorized_bundle_count": result.authorized_bundle_count,
            "denied_bundle_count": result.denied_bundle_count,
            "repair_attempt_count": result.repair_attempt_count,
        },
    }
    _assert_no_legacy_identity_fields(projection)
    assert_no_public_raw_references(
        projection,
        "issue56_relation_projection_semantic_equivalence",
    )
    return projection


def build_issue56_diagnostic_composition(
    *,
    actor_workspace_id: str = ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    diagnostic_mode_id: str = ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
    sealed_source: Issue56SealedSourceDiagnosticInput | None = None,
    relation_projection_cache_role: str = "default",
) -> Issue56DiagnosticComposition:
    """Build one diagnostic query session and real connected ASGI application."""

    if relation_projection_cache_role not in {
        "default",
        "before_cold",
        "after_precomputed",
        "offline_cold_precomputed",
        "preexisting_precomputed",
    }:
        raise ContractValidationError("relation projection cache role is invalid")
    state = Issue56DiagnosticState()
    if sealed_source is None:
        if diagnostic_mode_id != ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID:
            raise ContractValidationError(
                "sealed-source diagnostic input is required for this mode"
            )
        session, effective_graph_view = _build_synthetic_semantic_fixture()
        allowed_relation_types = _ALLOWED_RELATIONS
        source_fixture_mode = "synthetic_non_sealed"
        sealed_source_asset_status = "not_exercised"
        source_asset_fingerprint = None
        loader_contract_fingerprint = None
        observation_inventory_fingerprint = None
        permission_lineage_fingerprint = None
        effective_graph_view_fingerprint = None
        graph_revision_fingerprint = None
        source_loader_binding_fingerprint = None
        source_binding_fingerprint = None
        source_observation_count = len(session.authorized_observations)
        lineage_crosswalk_precompute = None
        relation_projection_base_precompute = None
        prompt_selection = None
    else:
        if diagnostic_mode_id not in {
            ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
            ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
            _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
            _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
            _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
        }:
            raise ContractValidationError(
                "sealed-source diagnostic input cannot be used by another mode"
            )
        if sealed_source.diagnostic_mode_id != diagnostic_mode_id:
            raise ContractValidationError("sealed-source diagnostic composition mode mismatch")
        _validate_sealed_source_diagnostic_input(sealed_source)
        lineage_crosswalk_precompute = sealed_source.lineage_crosswalk_precompute
        relation_projection_base_precompute = sealed_source.relation_projection_base_precompute
        prompt_selection = sealed_source.prompt_selection
        session = sealed_source.session
        effective_graph_view = sealed_source.effective_graph_view
        allowed_relation_types = sealed_source.allowed_relation_types
        source_fixture_mode = (
            "sealed_source_real_prompt_relation_projection_equivalence"
            if diagnostic_mode_id in _RELATION_PROJECTION_EQUIVALENCE_MODE_IDS
            else "sealed_source_real_prompt"
            if diagnostic_mode_id == ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
            else "sealed_source"
        )
        sealed_source_asset_status = "validated_and_exercised"
        source_asset_fingerprint = sealed_source.source_asset_fingerprint
        loader_contract_fingerprint = sealed_source.loader_contract_fingerprint
        observation_inventory_fingerprint = sealed_source.observation_inventory_fingerprint
        permission_lineage_fingerprint = sealed_source.permission_lineage_fingerprint
        effective_graph_view_fingerprint = sealed_source.effective_graph_view_fingerprint
        graph_revision_fingerprint = sealed_source.graph_revision_fingerprint
        source_loader_binding_fingerprint = sealed_source.source_loader_binding_fingerprint
        source_binding_fingerprint = sealed_source.source_binding_fingerprint
        source_observation_count = sealed_source.observation_count
        state.lineage_crosswalk_precompute_count = (
            lineage_crosswalk_precompute.helper_invocation_count
        )
        state.lineage_crosswalk_precompute_elapsed_ms = lineage_crosswalk_precompute.elapsed_ms
        state.lineage_crosswalk_cache_hit_status = "expected"
        state.precomputed_lineage_crosswalk_fingerprint = (
            lineage_crosswalk_precompute.crosswalk_fingerprint
        )
        state.relation_projection_base_precompute_count = (
            relation_projection_base_precompute.helper_invocation_count
        )
        state.relation_projection_base_precompute_elapsed_ms = (
            relation_projection_base_precompute.elapsed_ms
        )
        state.relation_projection_base_cache_status = (
            "cold_reference"
            if relation_projection_cache_role == "before_cold"
            else relation_projection_base_precompute.cache_status
        )
    config = Issue56DiagnosticConfig()
    google_client = object()
    bridge = Issue56DiagnosticOAuthBridge(
        config=config,
        google_client=google_client,
        state=state,
        actor_workspace_id=actor_workspace_id,
    )

    def retrieval_handler(arguments: dict[str, Any]) -> dict[str, Any]:
        state.semantic_handler_count += 1
        state.boundary_events.append("semantic_gateway_handler")
        if not state.boundary_events or "dispatcher_authorized" not in state.boundary_events:
            raise ContractValidationError("diagnostic authorization audit must precede retrieval")
        expected_keys = {
            "query_text",
            "requester_user_id",
            "session_id",
            "workspace_id",
        }
        if set(arguments) != expected_keys:
            raise ContractValidationError("diagnostic handler arguments are invalid")
        if (
            arguments["requester_user_id"] != ISSUE56_DIAGNOSTIC_USER_ID
            or arguments["workspace_id"] != ISSUE56_DIAGNOSTIC_WORKSPACE_ID
            or arguments["session_id"] != _TOKEN_SESSION_ID
        ):
            raise ContractValidationError("diagnostic actor injection mismatch")
        state.handler_requester_user_id = arguments["requester_user_id"]
        state.handler_workspace_id = arguments["workspace_id"]
        state.handler_session_id = arguments["session_id"]
        state.handler_argument_fingerprint = sha256_json(
            {
                "query_hash": sha256_json(arguments["query_text"]),
                "requester_user_id": arguments["requester_user_id"],
                "workspace_id": arguments["workspace_id"],
                "session_id": arguments["session_id"],
            }
        )
        with state.measure("semantic_gateway_handler"):
            phase_trace = SemanticPhaseTrace()
            with state.measure("authorized_semantic_mail_session_query"):
                state.hybrid_query_count += 1
                state.boundary_events.append("authorized_semantic_mail_session_query")
                result = session.query(
                    query_text=arguments["query_text"],
                    effective_graph_view=effective_graph_view,
                    allowed_relation_types=allowed_relation_types,
                    phase_trace=phase_trace,
                )
            state.last_semantic_phase_trace = phase_trace.to_safe_dict()
            if lineage_crosswalk_precompute is not None:
                semantic_lineage_phase = next(
                    (
                        phase
                        for phase in state.last_semantic_phase_trace.get(
                            "phases",
                            (),
                        )
                        if phase.get("phase") == "lineage_crosswalk"
                    ),
                    None,
                )
                if (
                    semantic_lineage_phase is None
                    or semantic_lineage_phase.get("outcome") != "completed"
                ):
                    state.lineage_crosswalk_cache_hit_status = "blocked"
                elif (
                    result.lineage_audit is not None
                    and result.lineage_audit.crosswalk_fingerprint
                    == state.precomputed_lineage_crosswalk_fingerprint
                ):
                    state.lineage_crosswalk_cache_hit_status = "passed"
                    state.lineage_crosswalk_query_binding_status = "passed"
                elif result.status == "no_answer" and (
                    "semantic_query_time_budget_exhausted" in result.warnings
                ):
                    state.lineage_crosswalk_cache_hit_status = "passed"
                    state.lineage_crosswalk_query_binding_status = "not_reached_before_deadline"
                else:
                    raise ContractValidationError("sealed-source lineage query binding mismatch")
            with state.measure("governed_answer_render"):
                state.answer_render_count += 1
                state.boundary_events.append("governed_answer_render")
                answer = render_governed_evidence_answer(result)
            state.last_semantic_equivalence = _semantic_equivalence_projection(
                result=result,
                answer=answer,
                permission_lineage_fingerprint=permission_lineage_fingerprint,
                effective_graph_view_fingerprint=effective_graph_view_fingerprint,
                source_binding_fingerprint=source_binding_fingerprint,
                relation_projection_base_precompute=(relation_projection_base_precompute),
            )
        payload = {
            "status": result.status,
            "answer": {
                "status": answer.status,
                "answer_hash": answer.answer_hash,
                "source_result_fingerprint": answer.source_result_fingerprint,
                "citation_count": len(answer.citation_hashes),
            },
            "citations": list(answer.citation_hashes),
            "graph_hits": {"count": result.graph_path_count},
            "evidence": {
                "semantic_result_count": result.semantic_result_count,
                "citation_count": len(answer.citation_hashes),
            },
            "fallback_used": result.repair_attempt_count > 0,
            "fallback_reason": (
                None if not result.warnings else sha256_json(list(result.warnings))
            ),
            "evidence_coverage": {
                "authorized_citation_count": len(answer.citation_hashes),
            },
            "candidate_graph_proposal_seeds": [],
            "visible_graph_snippets": [],
            "redaction_counts": {"redacted_value_count": 0},
            "warnings": [sha256_json(warning) for warning in result.warnings],
            "diagnostic": {
                "query_hash": result.query_hash,
                "result_fingerprint": result.result_fingerprint,
                "runtime_method_fingerprint": result.runtime_method_fingerprint,
                "phase_trace": state.last_semantic_phase_trace,
            },
        }
        validate_public_gateway_payload(payload)
        return payload

    semantic_gateway = SemanticMcpGateway(retrieval_handler=retrieval_handler)

    def clock() -> datetime:
        return datetime(2026, 8, 20, 8, 0, 0, tzinfo=timezone.utc)

    base = create_connected_mcp_application(
        bridge=bridge,
        config=config,
        google_client=google_client,
        semantic_gateway=SemanticMcpGateway(),
        oauth_route_provider=lambda **_kwargs: [],
        clock=clock,
        environ={"FORMOWL_AUTH_MODE": "oauth_google"},
    )
    dispatcher = _Issue56DiagnosticDispatcher(
        bridge=bridge,
        config=config,
        semantic_gateway=semantic_gateway,
        clock=clock,
    )
    # Replace only this freshly-created in-memory server's handlers.  The
    # production module policy and every other app instance remain unchanged.
    base.server.list_tools()(dispatcher.list_tools)
    base.server.call_tool(validate_input=False)(dispatcher.call_tool)
    connected = ConnectedMcpApplication(
        app=base.app,
        server=base.server,
        session_manager=base.session_manager,
        dispatcher=dispatcher,
        bridge=bridge,
        config=config,
        manages_session_manager_lifespan=base.manages_session_manager_lifespan,
    )
    return Issue56DiagnosticComposition(
        application=connected,
        bridge=bridge,
        state=state,
        session=session,
        effective_graph_view=effective_graph_view,
        diagnostic_mode_id=diagnostic_mode_id,
        source_fixture_mode=source_fixture_mode,
        sealed_source_asset_status=sealed_source_asset_status,
        allowed_relation_types=allowed_relation_types,
        source_asset_fingerprint=source_asset_fingerprint,
        loader_contract_fingerprint=loader_contract_fingerprint,
        observation_inventory_fingerprint=observation_inventory_fingerprint,
        permission_lineage_fingerprint=permission_lineage_fingerprint,
        effective_graph_view_fingerprint=effective_graph_view_fingerprint,
        graph_revision_fingerprint=graph_revision_fingerprint,
        source_loader_binding_fingerprint=source_loader_binding_fingerprint,
        source_binding_fingerprint=source_binding_fingerprint,
        source_observation_count=source_observation_count,
        lineage_crosswalk_precompute=lineage_crosswalk_precompute,
        relation_projection_base_precompute=relation_projection_base_precompute,
        prompt_selection=prompt_selection,
        relation_projection_cache_role=relation_projection_cache_role,
    )


def build_issue56_relation_projection_equivalence_compositions(
    source: Issue56SealedSourceDiagnosticInput,
) -> tuple[Issue56DiagnosticComposition, Issue56DiagnosticComposition]:
    """Build isolated cold and precomputed views from one sealed source."""

    _validate_sealed_source_diagnostic_input(source)
    if source.diagnostic_mode_id not in _RELATION_PROJECTION_EQUIVALENCE_MODE_IDS:
        raise ContractValidationError("relation projection equivalence source mode mismatch")
    cold_view = EffectiveGraphView(
        requester_user_id=source.effective_graph_view.requester_user_id,
        user_graph_revision_id=source.effective_graph_view.user_graph_revision_id,
        canonical_graph_revision_id=(source.effective_graph_view.canonical_graph_revision_id),
        ontology_revision_id=source.effective_graph_view.ontology_revision_id,
        assembly_policy_id=source.effective_graph_view.assembly_policy_id,
        visible_nodes=list(source.effective_graph_view.visible_nodes),
        visible_edges=list(source.effective_graph_view.visible_edges),
        access_required=list(source.effective_graph_view.access_required),
        applied_grant_ids=list(source.effective_graph_view.applied_grant_ids),
    )
    cold_source = build_issue56_sealed_source_diagnostic_input(
        session=source.session,
        effective_graph_view=cold_view,
        allowed_relation_types=source.allowed_relation_types,
        source_asset_fingerprint=source.source_asset_fingerprint,
        loader_contract_fingerprint=source.loader_contract_fingerprint,
        graph_revision_fingerprint=source.graph_revision_fingerprint,
        source_loader_binding_fingerprint=(source.source_loader_binding_fingerprint),
        lineage_crosswalk_precompute=(source.lineage_crosswalk_precompute.to_safe_dict()),
        relation_projection_base_precompute=(
            source.relation_projection_base_precompute.to_safe_dict()
        ),
        private_prompt=source.private_prompt,
        prompt_selection=(
            source.prompt_selection.to_safe_dict() if source.prompt_selection is not None else None
        ),
        diagnostic_mode_id=source.diagnostic_mode_id,
    )
    if (
        cold_source.source_binding_fingerprint != source.source_binding_fingerprint
        or cold_source.observation_inventory_fingerprint != source.observation_inventory_fingerprint
        or cold_source.permission_lineage_fingerprint != source.permission_lineage_fingerprint
        or cold_source.effective_graph_view_fingerprint != source.effective_graph_view_fingerprint
        or cold_source.graph_revision_fingerprint != source.graph_revision_fingerprint
    ):
        raise ContractValidationError("relation projection cold view source binding mismatch")
    before = build_issue56_diagnostic_composition(
        diagnostic_mode_id=source.diagnostic_mode_id,
        sealed_source=cold_source,
        relation_projection_cache_role="before_cold",
    )
    after = build_issue56_diagnostic_composition(
        diagnostic_mode_id=source.diagnostic_mode_id,
        sealed_source=source,
        relation_projection_cache_role="after_precomputed",
    )
    if (
        before.effective_graph_view is after.effective_graph_view
        or before.session is not after.session
        or before.source_binding_fingerprint != after.source_binding_fingerprint
        or before.permission_lineage_fingerprint != after.permission_lineage_fingerprint
        or before.effective_graph_view_fingerprint != after.effective_graph_view_fingerprint
        or before.graph_revision_fingerprint != after.graph_revision_fingerprint
    ):
        raise ContractValidationError(
            "relation projection equivalence composition isolation mismatch"
        )
    return before, after


def build_issue56_relation_projection_equivalence_v6_compositions(
    source: Issue56SealedSourceDiagnosticInput,
    *,
    graph_content_snapshot_materializer: (Callable[..., Any] | None) = None,
) -> tuple[
    Issue56DiagnosticComposition,
    Issue56DiagnosticComposition,
    Issue56GraphContentPresealEvidence,
]:
    """Build v6 arms with graph content sealed before the exactly-once claim."""

    _validate_sealed_source_diagnostic_input(source)
    if source.diagnostic_mode_id not in _RELATION_PROJECTION_EQUIVALENCE_V6_MODE_IDS:
        raise ContractValidationError("relation projection v6 source mode mismatch")
    if graph_content_snapshot_materializer is None:
        from formowl_mail import precompute_effective_graph_content_snapshot

        graph_content_snapshot_materializer = precompute_effective_graph_content_snapshot
    if not callable(graph_content_snapshot_materializer):
        raise ContractValidationError(
            "effective graph content snapshot materializer is unavailable"
        )

    cold_view = _copy_effective_graph_view(source.effective_graph_view)
    before_started_at = time.perf_counter()
    owner_materialization = graph_content_snapshot_materializer(
        session=source.session,
        effective_graph_view=cold_view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
        expected_effective_graph_view_fingerprint=(source.effective_graph_view_fingerprint),
    )
    before_preseal_elapsed_ms = round(
        (time.perf_counter() - before_started_at) * 1_000.0,
        6,
    )
    owner_materialization_safe = _safe_owner_graph_content_materialization(owner_materialization)
    owner_counts = owner_materialization_safe["counts"]
    if (
        owner_materialization_safe.get("status") != "passed"
        or owner_materialization_safe.get("snapshot_status")
        != "materialized_relation_projection_caches_cold"
        or owner_materialization_safe.get("graph_revision_fingerprint")
        != source.graph_revision_fingerprint
        or owner_materialization_safe.get("effective_graph_view_fingerprint")
        != source.effective_graph_view_fingerprint
        or owner_materialization_safe.get("source_session_binding_fingerprint")
        != source.session.source_session_binding_fingerprint
        or owner_materialization_safe.get("source_access_fingerprint")
        != source.session.authorized_source.authorization_fingerprint
        or owner_materialization_safe.get("permission_lineage_fingerprint")
        != source.permission_lineage_fingerprint
        or owner_materialization_safe.get("index_fingerprint")
        != source.session.index.index_fingerprint
        or owner_materialization_safe.get("candidate_admission_profile_fingerprint")
        != source.session.index.profile_fingerprint
        or owner_materialization_safe.get("authorized_observation_set_fingerprint")
        != source.relation_projection_base_precompute.authorized_observation_set_fingerprint
        or owner_counts["authorized_observation_count"] != source.observation_count
        or owner_counts["source_scope_count"] != len(source.session.authorized_source_scope_ids)
        or owner_counts["node_count"] != len(cold_view.visible_nodes)
        or owner_counts["edge_count"] != len(cold_view.visible_edges)
        or owner_counts["access_required_count"] != len(cold_view.access_required)
        or owner_counts["applied_grant_count"] != len(cold_view.applied_grant_ids)
        or owner_counts["relation_projection_cache_binding_entry_count"] != 0
        or owner_counts["relation_projection_base_entry_count"] != 0
    ):
        raise ContractValidationError(
            "effective graph content snapshot materialization binding mismatch"
        )

    after_started_at = time.perf_counter()
    after_snapshot_state = _effective_graph_snapshot_cache_state(
        source.effective_graph_view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
    )
    after_snapshot_validation_elapsed_ms = round(
        (time.perf_counter() - after_started_at) * 1_000.0,
        6,
    )
    before_snapshot_state = _effective_graph_snapshot_cache_state(
        cold_view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
    )
    expected_cache_binding = source.relation_projection_base_precompute.cache_binding_fingerprint
    if (
        before_snapshot_state["binding_entry_count"] != 0
        or before_snapshot_state["base_entry_count"] != 0
        or after_snapshot_state["binding_entry_count"] != 1
        or after_snapshot_state["base_entry_count"] != 1
        or expected_cache_binding not in after_snapshot_state["base_cache_container"]
        or not any(
            getattr(binding, "cache_binding_fingerprint", None) == expected_cache_binding
            for binding in after_snapshot_state["binding_cache_container"].values()
        )
    ):
        raise ContractValidationError(
            "relation projection v6 graph snapshot cache preflight mismatch"
        )
    if (
        before_snapshot_state["snapshot"] is after_snapshot_state["snapshot"]
        or before_snapshot_state["lock"] is after_snapshot_state["lock"]
        or before_snapshot_state["binding_cache_container"]
        is after_snapshot_state["binding_cache_container"]
        or before_snapshot_state["base_cache_container"]
        is after_snapshot_state["base_cache_container"]
    ):
        raise ContractValidationError("relation projection v6 graph snapshot isolation mismatch")

    cold_source = build_issue56_sealed_source_diagnostic_input(
        session=source.session,
        effective_graph_view=cold_view,
        allowed_relation_types=source.allowed_relation_types,
        source_asset_fingerprint=source.source_asset_fingerprint,
        loader_contract_fingerprint=source.loader_contract_fingerprint,
        graph_revision_fingerprint=source.graph_revision_fingerprint,
        source_loader_binding_fingerprint=(source.source_loader_binding_fingerprint),
        lineage_crosswalk_precompute=(source.lineage_crosswalk_precompute.to_safe_dict()),
        relation_projection_base_precompute=(
            source.relation_projection_base_precompute.to_safe_dict()
        ),
        private_prompt=source.private_prompt,
        prompt_selection=(
            source.prompt_selection.to_safe_dict() if source.prompt_selection is not None else None
        ),
        diagnostic_mode_id=source.diagnostic_mode_id,
    )
    if (
        cold_source.source_binding_fingerprint != source.source_binding_fingerprint
        or cold_source.observation_inventory_fingerprint != source.observation_inventory_fingerprint
        or cold_source.permission_lineage_fingerprint != source.permission_lineage_fingerprint
        or cold_source.effective_graph_view_fingerprint != source.effective_graph_view_fingerprint
        or cold_source.graph_revision_fingerprint != source.graph_revision_fingerprint
    ):
        raise ContractValidationError("relation projection v6 cold view source binding mismatch")

    before = build_issue56_diagnostic_composition(
        diagnostic_mode_id=source.diagnostic_mode_id,
        sealed_source=cold_source,
        relation_projection_cache_role="before_cold",
    )
    after = build_issue56_diagnostic_composition(
        diagnostic_mode_id=source.diagnostic_mode_id,
        sealed_source=source,
        relation_projection_cache_role="after_precomputed",
    )
    if (
        before.session is not after.session
        or before.source_binding_fingerprint != after.source_binding_fingerprint
        or before.permission_lineage_fingerprint != after.permission_lineage_fingerprint
        or before.effective_graph_view_fingerprint != after.effective_graph_view_fingerprint
        or before.graph_revision_fingerprint != after.graph_revision_fingerprint
    ):
        raise ContractValidationError("relation projection v6 composition binding mismatch")

    evidence_payload = {
        "status": "passed",
        "cache_status": "before_content_only_after_relation_primed",
        "helper_invocation_count": 1,
        "before_preseal_elapsed_ms": before_preseal_elapsed_ms,
        "after_snapshot_validation_elapsed_ms": (after_snapshot_validation_elapsed_ms),
        "session_binding_fingerprint": owner_materialization_safe[
            "source_session_binding_fingerprint"
        ],
        "source_access_fingerprint": owner_materialization_safe["source_access_fingerprint"],
        "source_binding_fingerprint": source.source_binding_fingerprint,
        "permission_lineage_fingerprint": (source.permission_lineage_fingerprint),
        "effective_graph_view_fingerprint": (source.effective_graph_view_fingerprint),
        "graph_revision_fingerprint": source.graph_revision_fingerprint,
        "graph_content_fingerprint": owner_materialization_safe["graph_content_fingerprint"],
        "index_fingerprint": source.session.index.index_fingerprint,
        "candidate_admission_profile_fingerprint": (source.session.index.profile_fingerprint),
        "authorized_observation_set_fingerprint": (
            source.relation_projection_base_precompute.authorized_observation_set_fingerprint
        ),
        "owner_precompute_fingerprint": owner_materialization_safe["precompute_fingerprint"],
        "authorized_observation_count": owner_counts["authorized_observation_count"],
        "source_scope_count": owner_counts["source_scope_count"],
        "node_count": owner_counts["node_count"],
        "edge_count": owner_counts["edge_count"],
        "access_required_count": owner_counts["access_required_count"],
        "applied_grant_count": owner_counts["applied_grant_count"],
        "before_binding_cache_entry_count": (before_snapshot_state["binding_entry_count"]),
        "before_base_cache_entry_count": (before_snapshot_state["base_entry_count"]),
        "after_binding_cache_entry_count": (after_snapshot_state["binding_entry_count"]),
        "after_base_cache_entry_count": (after_snapshot_state["base_entry_count"]),
    }
    evidence = Issue56GraphContentPresealEvidence(
        **evidence_payload,
        evidence_binding_fingerprint=sha256_json(
            {
                "artifact_id": "formowl_issue56_graph_content_preseal_safe_v1",
                "schema_version": 1,
                **evidence_payload,
            }
        ),
    )
    return before, after, evidence


def build_issue56_relation_projection_offline_equivalence_v7_compositions(
    source: Issue56SealedSourceDiagnosticInput,
    *,
    graph_content_snapshot_materializer: Callable[..., Any] | None = None,
    relation_projection_base_precomputer: Callable[..., Any] | None = None,
) -> tuple[
    Issue56DiagnosticComposition,
    Issue56DiagnosticComposition,
    Issue56OfflineEquivalencePreflightEvidence,
]:
    """Preflight two isolated graph snapshots and prime only the after arm."""

    _validate_sealed_source_diagnostic_input(source)
    if source.diagnostic_mode_id not in _RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_MODE_IDS:
        raise ContractValidationError("relation projection v7 source mode mismatch")
    if graph_content_snapshot_materializer is None:
        from formowl_mail import precompute_effective_graph_content_snapshot

        graph_content_snapshot_materializer = precompute_effective_graph_content_snapshot
    if relation_projection_base_precomputer is None:
        from formowl_mail.hybrid import precompute_relation_projection_base

        relation_projection_base_precomputer = precompute_relation_projection_base
    if not callable(graph_content_snapshot_materializer) or not callable(
        relation_projection_base_precomputer
    ):
        raise ContractValidationError("relation projection v7 owner helper is unavailable")

    cold_view = _copy_effective_graph_view(source.effective_graph_view)
    after_view = _copy_effective_graph_view(source.effective_graph_view)
    materializations: list[tuple[Mapping[str, Any], float]] = []
    for selected_view in (cold_view, after_view):
        started_at = time.perf_counter()
        owner_materialization = graph_content_snapshot_materializer(
            session=source.session,
            effective_graph_view=selected_view,
            expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
            expected_effective_graph_view_fingerprint=(source.effective_graph_view_fingerprint),
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1_000.0, 6)
        safe_materialization = _safe_owner_graph_content_materialization(owner_materialization)
        materializations.append((safe_materialization, elapsed_ms))

    cold_materialization, cold_preseal_elapsed_ms = materializations[0]
    after_materialization, after_preseal_elapsed_ms = materializations[1]
    cold_counts = cold_materialization["counts"]
    after_counts = after_materialization["counts"]
    expected_observation_set = (
        source.relation_projection_base_precompute.authorized_observation_set_fingerprint
    )
    for safe_materialization, counts, selected_view in (
        (cold_materialization, cold_counts, cold_view),
        (after_materialization, after_counts, after_view),
    ):
        if (
            safe_materialization.get("status") != "passed"
            or safe_materialization.get("snapshot_status")
            != "materialized_relation_projection_caches_cold"
            or safe_materialization.get("graph_revision_fingerprint")
            != source.graph_revision_fingerprint
            or safe_materialization.get("effective_graph_view_fingerprint")
            != source.effective_graph_view_fingerprint
            or safe_materialization.get("source_session_binding_fingerprint")
            != source.session.source_session_binding_fingerprint
            or safe_materialization.get("source_access_fingerprint")
            != source.session.authorized_source.authorization_fingerprint
            or safe_materialization.get("permission_lineage_fingerprint")
            != source.permission_lineage_fingerprint
            or safe_materialization.get("index_fingerprint")
            != source.session.index.index_fingerprint
            or safe_materialization.get("candidate_admission_profile_fingerprint")
            != source.session.index.profile_fingerprint
            or safe_materialization.get("authorized_observation_set_fingerprint")
            != expected_observation_set
            or counts["authorized_observation_count"] != source.observation_count
            or counts["source_scope_count"] != len(source.session.authorized_source_scope_ids)
            or counts["node_count"] != len(selected_view.visible_nodes)
            or counts["edge_count"] != len(selected_view.visible_edges)
            or counts["access_required_count"] != len(selected_view.access_required)
            or counts["applied_grant_count"] != len(selected_view.applied_grant_ids)
            or counts["relation_projection_cache_binding_entry_count"] != 0
            or counts["relation_projection_base_entry_count"] != 0
        ):
            raise ContractValidationError("relation projection v7 graph preseal binding mismatch")
    if (
        cold_materialization["graph_content_fingerprint"]
        != after_materialization["graph_content_fingerprint"]
        or cold_materialization["precompute_fingerprint"]
        != after_materialization["precompute_fingerprint"]
        or cold_counts != after_counts
    ):
        raise ContractValidationError("relation projection v7 graph preseal drift")

    cold_snapshot_state = _effective_graph_snapshot_cache_state(
        cold_view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
    )
    after_snapshot_state = _effective_graph_snapshot_cache_state(
        after_view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
    )
    if (
        cold_snapshot_state["binding_entry_count"] != 0
        or cold_snapshot_state["base_entry_count"] != 0
        or after_snapshot_state["binding_entry_count"] != 0
        or after_snapshot_state["base_entry_count"] != 0
        or cold_view is after_view
        or cold_snapshot_state["snapshot"] is after_snapshot_state["snapshot"]
        or cold_snapshot_state["lock"] is after_snapshot_state["lock"]
        or cold_snapshot_state["binding_cache_container"]
        is after_snapshot_state["binding_cache_container"]
        or cold_snapshot_state["base_cache_container"]
        is after_snapshot_state["base_cache_container"]
    ):
        raise ContractValidationError("relation projection v7 graph isolation mismatch")

    after_precompute_started_at = time.perf_counter()
    after_owner_precompute = relation_projection_base_precomputer(
        session=source.session,
        effective_graph_view=after_view,
    )
    after_precompute_elapsed_ms = round(
        (time.perf_counter() - after_precompute_started_at) * 1_000.0,
        6,
    )
    after_owner_precompute_safe = _safe_owner_relation_projection_base_precompute(
        after_owner_precompute
    )
    expected_relation_precompute = source.relation_projection_base_precompute
    if (
        after_owner_precompute_safe["status"] != "passed"
        or after_owner_precompute_safe["cache_status"] != "primed"
        or after_owner_precompute_safe["cache_binding_fingerprint"]
        != expected_relation_precompute.cache_binding_fingerprint
        or after_owner_precompute_safe["graph_revision_fingerprint"]
        != source.graph_revision_fingerprint
        or after_owner_precompute_safe["index_fingerprint"]
        != source.session.index.index_fingerprint
        or after_owner_precompute_safe["candidate_admission_profile_fingerprint"]
        != source.session.index.profile_fingerprint
        or after_owner_precompute_safe["authorized_observation_set_fingerprint"]
        != expected_relation_precompute.authorized_observation_set_fingerprint
        or after_owner_precompute_safe["candidate_set_fingerprint"]
        != expected_relation_precompute.candidate_set_fingerprint
        or after_owner_precompute_safe["precompute_fingerprint"]
        != expected_relation_precompute.precompute_fingerprint
        or after_owner_precompute_safe["counts"]
        != expected_relation_precompute.to_safe_dict()["counts"]
    ):
        raise ContractValidationError("relation projection v7 after precompute binding mismatch")
    after_snapshot_state = _effective_graph_snapshot_cache_state(
        after_view,
        expected_graph_revision_fingerprint=source.graph_revision_fingerprint,
    )
    if (
        cold_snapshot_state["binding_entry_count"] != 0
        or cold_snapshot_state["base_entry_count"] != 0
        or after_snapshot_state["binding_entry_count"] != 1
        or after_snapshot_state["base_entry_count"] != 1
        or expected_relation_precompute.cache_binding_fingerprint
        not in after_snapshot_state["base_cache_container"]
        or not any(
            getattr(binding, "cache_binding_fingerprint", None)
            == expected_relation_precompute.cache_binding_fingerprint
            for binding in after_snapshot_state["binding_cache_container"].values()
        )
    ):
        raise ContractValidationError("relation projection v7 cache preflight mismatch")

    cold_source = _copy_sealed_source_with_view(source, cold_view)
    after_source = _copy_sealed_source_with_view(source, after_view)
    before = build_issue56_diagnostic_composition(
        diagnostic_mode_id=source.diagnostic_mode_id,
        sealed_source=cold_source,
        relation_projection_cache_role="offline_cold_precomputed",
    )
    after = build_issue56_diagnostic_composition(
        diagnostic_mode_id=source.diagnostic_mode_id,
        sealed_source=after_source,
        relation_projection_cache_role="preexisting_precomputed",
    )
    if (
        before.session is not after.session
        or before.effective_graph_view is after.effective_graph_view
        or before.source_binding_fingerprint != after.source_binding_fingerprint
        or before.permission_lineage_fingerprint != after.permission_lineage_fingerprint
        or before.effective_graph_view_fingerprint != after.effective_graph_view_fingerprint
        or before.graph_revision_fingerprint != after.graph_revision_fingerprint
        or before.state.hybrid_query_count != 0
        or after.state.hybrid_query_count != 0
        or before.state.authentication_count != 0
        or after.state.authentication_count != 0
    ):
        raise ContractValidationError("relation projection v7 composition preflight mismatch")

    evidence_payload = {
        "status": "passed",
        "cache_status": "cold_0_0_after_1_1_before_claim",
        "graph_preseal_helper_invocation_count": 2,
        "after_relation_precompute_helper_invocation_count": 1,
        "cold_graph_preseal_elapsed_ms": cold_preseal_elapsed_ms,
        "after_graph_preseal_elapsed_ms": after_preseal_elapsed_ms,
        "after_relation_precompute_elapsed_ms": after_precompute_elapsed_ms,
        "session_binding_fingerprint": cold_materialization["source_session_binding_fingerprint"],
        "source_access_fingerprint": cold_materialization["source_access_fingerprint"],
        "source_binding_fingerprint": source.source_binding_fingerprint,
        "permission_lineage_fingerprint": source.permission_lineage_fingerprint,
        "effective_graph_view_fingerprint": source.effective_graph_view_fingerprint,
        "graph_revision_fingerprint": source.graph_revision_fingerprint,
        "graph_content_fingerprint": cold_materialization["graph_content_fingerprint"],
        "index_fingerprint": source.session.index.index_fingerprint,
        "candidate_admission_profile_fingerprint": source.session.index.profile_fingerprint,
        "authorized_observation_set_fingerprint": expected_observation_set,
        "cold_graph_preseal_fingerprint": cold_materialization["precompute_fingerprint"],
        "after_graph_preseal_fingerprint": after_materialization["precompute_fingerprint"],
        "relation_projection_precompute_fingerprint": (
            expected_relation_precompute.precompute_fingerprint
        ),
        "relation_projection_cache_binding_fingerprint": (
            expected_relation_precompute.cache_binding_fingerprint
        ),
        "authorized_observation_count": cold_counts["authorized_observation_count"],
        "source_scope_count": cold_counts["source_scope_count"],
        "node_count": cold_counts["node_count"],
        "edge_count": cold_counts["edge_count"],
        "access_required_count": cold_counts["access_required_count"],
        "applied_grant_count": cold_counts["applied_grant_count"],
        "cold_binding_cache_entry_count": (cold_snapshot_state["binding_entry_count"]),
        "cold_base_cache_entry_count": cold_snapshot_state["base_entry_count"],
        "after_binding_cache_entry_count": (after_snapshot_state["binding_entry_count"]),
        "after_base_cache_entry_count": after_snapshot_state["base_entry_count"],
    }
    evidence = Issue56OfflineEquivalencePreflightEvidence(
        **evidence_payload,
        evidence_binding_fingerprint=sha256_json(
            {
                "artifact_id": (
                    "formowl_issue56_relation_projection_offline_equivalence_" "preflight_safe_v1"
                ),
                "schema_version": 1,
                **evidence_payload,
            }
        ),
    )
    evidence.to_safe_dict()
    return before, after, evidence


def _copy_sealed_source_with_view(
    source: Issue56SealedSourceDiagnosticInput,
    effective_graph_view: EffectiveGraphView,
) -> Issue56SealedSourceDiagnosticInput:
    copied = build_issue56_sealed_source_diagnostic_input(
        session=source.session,
        effective_graph_view=effective_graph_view,
        allowed_relation_types=source.allowed_relation_types,
        source_asset_fingerprint=source.source_asset_fingerprint,
        loader_contract_fingerprint=source.loader_contract_fingerprint,
        graph_revision_fingerprint=source.graph_revision_fingerprint,
        source_loader_binding_fingerprint=source.source_loader_binding_fingerprint,
        lineage_crosswalk_precompute=source.lineage_crosswalk_precompute.to_safe_dict(),
        relation_projection_base_precompute=(
            source.relation_projection_base_precompute.to_safe_dict()
        ),
        private_prompt=source.private_prompt,
        prompt_selection=(
            source.prompt_selection.to_safe_dict() if source.prompt_selection is not None else None
        ),
        diagnostic_mode_id=source.diagnostic_mode_id,
    )
    if (
        copied.source_binding_fingerprint != source.source_binding_fingerprint
        or copied.observation_inventory_fingerprint != source.observation_inventory_fingerprint
        or copied.permission_lineage_fingerprint != source.permission_lineage_fingerprint
        or copied.effective_graph_view_fingerprint != source.effective_graph_view_fingerprint
        or copied.graph_revision_fingerprint != source.graph_revision_fingerprint
    ):
        raise ContractValidationError("relation projection copied source binding mismatch")
    return copied


def _copy_effective_graph_view(
    effective_graph_view: EffectiveGraphView,
) -> EffectiveGraphView:
    return EffectiveGraphView(
        requester_user_id=effective_graph_view.requester_user_id,
        user_graph_revision_id=effective_graph_view.user_graph_revision_id,
        canonical_graph_revision_id=(effective_graph_view.canonical_graph_revision_id),
        ontology_revision_id=effective_graph_view.ontology_revision_id,
        assembly_policy_id=effective_graph_view.assembly_policy_id,
        visible_nodes=list(effective_graph_view.visible_nodes),
        visible_edges=list(effective_graph_view.visible_edges),
        access_required=list(effective_graph_view.access_required),
        applied_grant_ids=list(effective_graph_view.applied_grant_ids),
    )


def _safe_owner_graph_content_materialization(
    materialization: Any,
) -> Mapping[str, Any]:
    if isinstance(materialization, Mapping):
        safe = dict(materialization)
    else:
        to_safe_dict = getattr(materialization, "to_safe_dict", None)
        if not callable(to_safe_dict):
            raise ContractValidationError(
                "effective graph content snapshot materialization evidence is invalid"
            )
        safe = to_safe_dict()
    if not isinstance(safe, Mapping):
        raise ContractValidationError(
            "effective graph content snapshot materialization evidence is invalid"
        )
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "snapshot_status",
        "graph_revision_fingerprint",
        "graph_content_fingerprint",
        "effective_graph_view_fingerprint",
        "source_session_binding_fingerprint",
        "source_access_fingerprint",
        "permission_lineage_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "counts",
        "precompute_fingerprint",
    }
    expected_count_keys = {
        "authorized_observation_count",
        "source_scope_count",
        "node_count",
        "edge_count",
        "access_required_count",
        "applied_grant_count",
        "relation_projection_cache_binding_entry_count",
        "relation_projection_base_entry_count",
    }
    counts = safe.get("counts")
    fingerprint_fields = {
        "graph_revision_fingerprint",
        "graph_content_fingerprint",
        "effective_graph_view_fingerprint",
        "source_session_binding_fingerprint",
        "source_access_fingerprint",
        "permission_lineage_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "precompute_fingerprint",
    }
    if (
        set(safe) != expected_keys
        or safe.get("artifact_id")
        != "formowl_issue56_effective_graph_content_snapshot_precompute_v1"
        or safe.get("schema_version") != 1
        or safe.get("status") != "passed"
        or safe.get("snapshot_status") != "materialized_relation_projection_caches_cold"
        or not isinstance(counts, Mapping)
        or set(counts) != expected_count_keys
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        raise ContractValidationError(
            "effective graph content snapshot materialization evidence is invalid"
        )
    for field_name in fingerprint_fields:
        _require_sha256(
            str(safe.get(field_name, "")),
            f"effective graph content snapshot {field_name}",
        )
    expected_precompute_fingerprint = sha256_json(
        {
            "artifact_id": safe["artifact_id"],
            "graph_revision_fingerprint": safe["graph_revision_fingerprint"],
            "graph_content_fingerprint": safe["graph_content_fingerprint"],
            "effective_graph_view_fingerprint": (safe["effective_graph_view_fingerprint"]),
            "source_session_binding_fingerprint": (safe["source_session_binding_fingerprint"]),
            "source_access_fingerprint": safe["source_access_fingerprint"],
            "permission_lineage_fingerprint": (safe["permission_lineage_fingerprint"]),
            "index_fingerprint": safe["index_fingerprint"],
            "candidate_admission_profile_fingerprint": (
                safe["candidate_admission_profile_fingerprint"]
            ),
            "authorized_observation_set_fingerprint": (
                safe["authorized_observation_set_fingerprint"]
            ),
            **{key: counts[key] for key in expected_count_keys},
        }
    )
    if safe["precompute_fingerprint"] != expected_precompute_fingerprint:
        raise ContractValidationError(
            "effective graph content snapshot materialization seal mismatch"
        )
    _assert_no_legacy_identity_fields(safe)
    assert_no_public_raw_references(
        safe,
        "issue56_graph_content_snapshot_materialization",
    )
    return safe


def _safe_owner_relation_projection_base_precompute(
    precompute: Any,
) -> Mapping[str, Any]:
    if isinstance(precompute, Mapping):
        safe = dict(precompute)
    else:
        to_safe_dict = getattr(precompute, "to_safe_dict", None)
        if not callable(to_safe_dict):
            raise ContractValidationError(
                "relation projection base owner precompute evidence is invalid"
            )
        safe = to_safe_dict()
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "cache_status",
        "cache_binding_fingerprint",
        "graph_revision_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "counts",
        "precompute_fingerprint",
    }
    expected_count_keys = {
        "authorized_observation_count",
        "candidate_count",
        "projected_node_count",
        "observation_bound_node_group_count",
        "adjacency_node_count",
        "adjacency_transition_count",
        "authorized_index_vocabulary_hash_count",
        "authorized_graph_vocabulary_hash_count",
    }
    counts = safe.get("counts")
    if (
        not isinstance(safe, Mapping)
        or set(safe) != expected_keys
        or safe.get("artifact_id") != "formowl_issue56_relation_projection_base_precompute_v1"
        or safe.get("schema_version") != 1
        or safe.get("status") != "passed"
        or safe.get("cache_status") != "primed"
        or not isinstance(counts, Mapping)
        or set(counts) != expected_count_keys
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        raise ContractValidationError(
            "relation projection base owner precompute evidence is invalid"
        )
    for field_name in (
        "cache_binding_fingerprint",
        "graph_revision_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "precompute_fingerprint",
    ):
        _require_sha256(
            str(safe.get(field_name, "")),
            f"relation projection base owner {field_name}",
        )
    expected_precompute_fingerprint = sha256_json(
        {
            "artifact_id": safe["artifact_id"],
            "cache_binding_fingerprint": safe["cache_binding_fingerprint"],
            "graph_revision_fingerprint": safe["graph_revision_fingerprint"],
            "index_fingerprint": safe["index_fingerprint"],
            "tokenizer_profile_fingerprint": safe["candidate_admission_profile_fingerprint"],
            "authorized_observation_set_fingerprint": safe[
                "authorized_observation_set_fingerprint"
            ],
            "candidate_set_fingerprint": safe["candidate_set_fingerprint"],
            **{key: counts[key] for key in expected_count_keys},
        }
    )
    if safe["precompute_fingerprint"] != expected_precompute_fingerprint:
        raise ContractValidationError("relation projection base owner precompute seal mismatch")
    _assert_no_legacy_identity_fields(safe)
    assert_no_public_raw_references(
        safe,
        "issue56_relation_projection_base_owner_precompute",
    )
    return safe


def _effective_graph_snapshot_cache_state(
    effective_graph_view: EffectiveGraphView,
    *,
    expected_graph_revision_fingerprint: str,
) -> dict[str, Any]:
    snapshot = getattr(
        effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        None,
    )
    binding_cache = getattr(
        snapshot,
        "relation_projection_cache_binding_snapshots",
        None,
    )
    base_cache = getattr(snapshot, "relation_projection_bases", None)
    lock = getattr(snapshot, "relation_projection_base_lock", None)
    if (
        snapshot is None
        or getattr(snapshot, "graph_revision_fingerprint", None)
        != expected_graph_revision_fingerprint
        or not isinstance(binding_cache, Mapping)
        or not isinstance(base_cache, Mapping)
        or lock is None
    ):
        raise ContractValidationError("effective graph content snapshot cache state is invalid")
    return {
        "snapshot": snapshot,
        "lock": lock,
        "binding_cache_container": binding_cache,
        "base_cache_container": base_cache,
        "binding_entry_count": len(binding_cache),
        "base_entry_count": len(base_cache),
    }


def relation_projection_cache_evidence(
    composition: Issue56DiagnosticComposition,
) -> dict[str, Any]:
    """Inspect only hash/count cache state for one diagnostic composition."""

    expected = composition.relation_projection_base_precompute
    if expected is None:
        raise ContractValidationError("relation projection precompute evidence is unavailable")
    snapshot = getattr(
        composition.effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        None,
    )
    if snapshot is None:
        entry_count = 0
        expected_binding_present = False
        binding_snapshot_entry_count = 0
        expected_binding_snapshot_present = False
        snapshot_graph_binding_status = "not_materialized"
    else:
        relation_bases = getattr(snapshot, "relation_projection_bases", None)
        binding_snapshots = getattr(
            snapshot,
            "relation_projection_cache_binding_snapshots",
            None,
        )
        graph_revision_fingerprint = getattr(
            snapshot,
            "graph_revision_fingerprint",
            None,
        )
        if not isinstance(relation_bases, Mapping) or not isinstance(
            binding_snapshots,
            Mapping,
        ):
            raise ContractValidationError("relation projection cache container is invalid")
        if any(
            not isinstance(cache_key, str) or not cache_key.startswith("sha256:")
            for cache_key in relation_bases
        ):
            raise ContractValidationError("relation projection cache key is invalid")
        entry_count = len(relation_bases)
        expected_binding_present = expected.cache_binding_fingerprint in relation_bases
        binding_snapshot_entry_count = len(binding_snapshots)
        expected_binding_snapshot_present = any(
            getattr(binding_snapshot, "cache_binding_fingerprint", None)
            == expected.cache_binding_fingerprint
            for binding_snapshot in binding_snapshots.values()
        )
        snapshot_graph_binding_status = (
            "passed"
            if graph_revision_fingerprint == composition.graph_revision_fingerprint
            else "blocked"
        )
    evidence = {
        "cache_role": composition.relation_projection_cache_role,
        "entry_count": entry_count,
        "expected_binding_present": expected_binding_present,
        "binding_snapshot_entry_count": binding_snapshot_entry_count,
        "expected_binding_snapshot_present": expected_binding_snapshot_present,
        "snapshot_graph_binding_status": snapshot_graph_binding_status,
    }
    _assert_no_legacy_identity_fields(evidence)
    return evidence


def precompute_issue56_offline_relation_projection_base(
    composition: Issue56DiagnosticComposition,
    *,
    phase_traced_precomputer: Callable[..., Any] | None = None,
) -> Issue56OfflineRelationPrecomputeEvidence:
    """Invoke the owner cold precompute once, outside every user query budget."""

    if (
        composition.diagnostic_mode_id not in _RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_MODE_IDS
        or composition.relation_projection_cache_role != "offline_cold_precomputed"
        or composition.relation_projection_base_precompute is None
        or composition.effective_graph_view_fingerprint is None
        or composition.graph_revision_fingerprint is None
    ):
        raise ContractValidationError("offline relation projection precompute composition mismatch")
    cache_before = relation_projection_cache_evidence(composition)
    if (
        cache_before["binding_snapshot_entry_count"] != 0
        or cache_before["entry_count"] != 0
        or cache_before["expected_binding_snapshot_present"]
        or cache_before["expected_binding_present"]
        or cache_before["snapshot_graph_binding_status"] != "passed"
        or composition.state.hybrid_query_count != 0
        or composition.state.authentication_count != 0
    ):
        raise ContractValidationError(
            "offline relation projection precompute must start cold before query"
        )
    if phase_traced_precomputer is None:
        try:
            from formowl_mail import (
                precompute_relation_projection_base_cold_diagnostic,
            )
        except ImportError as exc:
            raise ContractValidationError(
                "relation projection phase-traced owner precompute helper is unavailable"
            ) from exc

        phase_traced_precomputer = precompute_relation_projection_base_cold_diagnostic
    if not callable(phase_traced_precomputer):
        raise ContractValidationError(
            "relation projection phase-traced owner precompute helper is unavailable"
        )
    precompute_started_at = time.perf_counter()
    owner_evidence = phase_traced_precomputer(
        session=composition.session,
        effective_graph_view=composition.effective_graph_view,
        expected_graph_revision_fingerprint=composition.graph_revision_fingerprint,
        expected_effective_graph_view_fingerprint=(composition.effective_graph_view_fingerprint),
    )
    total_elapsed_ms = round(
        (time.perf_counter() - precompute_started_at) * 1_000.0,
        6,
    )
    safe_owner_evidence = _safe_owner_relation_projection_phase_precompute(owner_evidence)
    cache_after = relation_projection_cache_evidence(composition)
    expected = composition.relation_projection_base_precompute
    if (
        cache_after["binding_snapshot_entry_count"] != 1
        or cache_after["entry_count"] != 1
        or not cache_after["expected_binding_snapshot_present"]
        or not cache_after["expected_binding_present"]
        or cache_after["snapshot_graph_binding_status"] != "passed"
        or composition.state.hybrid_query_count != 0
        or composition.state.authentication_count != 0
        or safe_owner_evidence["cache_binding_fingerprint"] != expected.cache_binding_fingerprint
        or safe_owner_evidence["graph_revision_fingerprint"]
        != composition.graph_revision_fingerprint
        or safe_owner_evidence["effective_graph_view_fingerprint"]
        != composition.effective_graph_view_fingerprint
        or safe_owner_evidence["index_fingerprint"] != composition.session.index.index_fingerprint
        or safe_owner_evidence["candidate_admission_profile_fingerprint"]
        != composition.session.index.profile_fingerprint
        or safe_owner_evidence["authorized_observation_set_fingerprint"]
        != expected.authorized_observation_set_fingerprint
        or safe_owner_evidence["candidate_set_fingerprint"] != expected.candidate_set_fingerprint
        or safe_owner_evidence["relation_projection_base_precompute_fingerprint"]
        != expected.precompute_fingerprint
        or safe_owner_evidence["source_session_binding_fingerprint"]
        != composition.session.source_session_binding_fingerprint
        or safe_owner_evidence["source_access_fingerprint"]
        != composition.session.authorized_source.authorization_fingerprint
        or safe_owner_evidence["permission_lineage_fingerprint"]
        != composition.permission_lineage_fingerprint
        or safe_owner_evidence["counts"] != expected.to_safe_dict()["counts"]
        or total_elapsed_ms
        < (
            safe_owner_evidence["phases"]["binding"]["elapsed_ms"]
            + safe_owner_evidence["phases"]["base_builder"]["elapsed_ms"]
        )
    ):
        raise ContractValidationError("offline relation projection precompute binding mismatch")
    phases = safe_owner_evidence["phases"]
    cache = safe_owner_evidence["cache"]
    evidence_payload = {
        "status": safe_owner_evidence["status"],
        "cache_status": "primed_from_cold",
        "helper_invocation_count": 1,
        "query_executed": False,
        "binding_snapshot_status": "completed",
        "base_builder_status": "completed",
        "binding_snapshot_elapsed_ms": round(
            float(phases["binding"]["elapsed_ms"]),
            6,
        ),
        "base_builder_elapsed_ms": round(
            float(phases["base_builder"]["elapsed_ms"]),
            6,
        ),
        "total_elapsed_ms": total_elapsed_ms,
        "binding_entry_count_before": cache["before"]["binding_entry_count"],
        "binding_entry_count_after": cache["after"]["binding_entry_count"],
        "base_entry_count_before": cache["before"]["base_entry_count"],
        "base_entry_count_after": cache["after"]["base_entry_count"],
        "cache_binding_fingerprint": safe_owner_evidence["cache_binding_fingerprint"],
        "graph_revision_fingerprint": safe_owner_evidence["graph_revision_fingerprint"],
        "effective_graph_view_fingerprint": safe_owner_evidence["effective_graph_view_fingerprint"],
        "index_fingerprint": safe_owner_evidence["index_fingerprint"],
        "candidate_admission_profile_fingerprint": safe_owner_evidence[
            "candidate_admission_profile_fingerprint"
        ],
        "authorized_observation_set_fingerprint": safe_owner_evidence[
            "authorized_observation_set_fingerprint"
        ],
        "candidate_set_fingerprint": safe_owner_evidence["candidate_set_fingerprint"],
        "precompute_fingerprint": safe_owner_evidence[
            "relation_projection_base_precompute_fingerprint"
        ],
        "owner_evidence_fingerprint": safe_owner_evidence["diagnostic_fingerprint"],
    }
    evidence = Issue56OfflineRelationPrecomputeEvidence(
        **evidence_payload,
        evidence_binding_fingerprint=sha256_json(
            {
                "artifact_id": ("formowl_issue56_relation_projection_offline_precompute_safe_v1"),
                "schema_version": 1,
                **evidence_payload,
            }
        ),
    )
    evidence.to_safe_dict()
    return evidence


def _safe_owner_relation_projection_phase_precompute(
    evidence: Any,
) -> Mapping[str, Any]:
    if isinstance(evidence, Mapping):
        safe = dict(evidence)
    else:
        to_safe_dict = getattr(evidence, "to_safe_dict", None)
        if not callable(to_safe_dict):
            raise ContractValidationError(
                "relation projection phase-traced owner evidence is invalid"
            )
        safe = to_safe_dict()
    expected_keys = {
        "artifact_id",
        "schema_version",
        "status",
        "claim_boundary",
        "deadline_mode",
        "phases",
        "cache",
        "cache_binding_fingerprint",
        "graph_revision_fingerprint",
        "graph_content_fingerprint",
        "effective_graph_view_fingerprint",
        "source_session_binding_fingerprint",
        "source_access_fingerprint",
        "permission_lineage_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "relation_projection_base_precompute_fingerprint",
        "counts",
        "diagnostic_fingerprint",
    }
    phases = safe.get("phases")
    cache = safe.get("cache")
    if (
        not isinstance(safe, Mapping)
        or set(safe) != expected_keys
        or safe.get("artifact_id") != "formowl_issue56_relation_projection_base_cold_diagnostic_v1"
        or safe.get("schema_version") != 1
        or safe.get("status") != "passed"
        or safe.get("claim_boundary") != "diagnostic_only_not_query_or_methodology_evidence"
        or safe.get("deadline_mode") != "offline_no_query_deadline"
        or not isinstance(phases, Mapping)
        or set(phases) != {"binding", "base_builder"}
        or not isinstance(cache, Mapping)
        or set(cache) != {"before", "after"}
        or cache.get("before") != {"binding_entry_count": 0, "base_entry_count": 0}
        or cache.get("after") != {"binding_entry_count": 1, "base_entry_count": 1}
    ):
        raise ContractValidationError("relation projection phase-traced owner evidence is invalid")
    for phase_name in ("binding", "base_builder"):
        phase = phases.get(phase_name)
        if (
            not isinstance(phase, Mapping)
            or set(phase)
            != {
                "started",
                "completed",
                "elapsed_ms",
                "invocation_count",
                "publication_status",
            }
            or phase.get("started") is not True
            or phase.get("completed") is not True
            or phase.get("invocation_count") != 1
            or phase.get("publication_status") != "published"
            or isinstance(phase.get("elapsed_ms"), bool)
            or not isinstance(phase.get("elapsed_ms"), (int, float))
            or phase["elapsed_ms"] < 0
        ):
            raise ContractValidationError("relation projection phase-traced owner phase is invalid")
    for field_name in (
        "cache_binding_fingerprint",
        "graph_revision_fingerprint",
        "graph_content_fingerprint",
        "effective_graph_view_fingerprint",
        "source_session_binding_fingerprint",
        "source_access_fingerprint",
        "permission_lineage_fingerprint",
        "index_fingerprint",
        "candidate_admission_profile_fingerprint",
        "authorized_observation_set_fingerprint",
        "candidate_set_fingerprint",
        "relation_projection_base_precompute_fingerprint",
        "diagnostic_fingerprint",
    ):
        _require_sha256(
            str(safe.get(field_name, "")),
            f"relation projection phase-traced owner {field_name}",
        )
    counts = safe.get("counts")
    expected_count_keys = {
        "authorized_observation_count",
        "candidate_count",
        "projected_node_count",
        "observation_bound_node_group_count",
        "adjacency_node_count",
        "adjacency_transition_count",
        "authorized_index_vocabulary_hash_count",
        "authorized_graph_vocabulary_hash_count",
    }
    if (
        not isinstance(counts, Mapping)
        or set(counts) != expected_count_keys
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        raise ContractValidationError("relation projection phase-traced owner counts are invalid")
    supplied_evidence_fingerprint = safe["diagnostic_fingerprint"]
    before_cache = cache["before"]
    after_cache = cache["after"]
    if (
        not isinstance(before_cache, Mapping)
        or not isinstance(after_cache, Mapping)
        or set(before_cache) != {"binding_entry_count", "base_entry_count"}
        or set(after_cache) != {"binding_entry_count", "base_entry_count"}
    ):
        raise ContractValidationError("relation projection phase-traced owner cache is invalid")
    binding_phase = phases["binding"]
    base_builder_phase = phases["base_builder"]
    fingerprint_payload = {
        "artifact_id": safe["artifact_id"],
        "schema_version": safe["schema_version"],
        "status": safe["status"],
        "claim_boundary": safe["claim_boundary"],
        "deadline_mode": safe["deadline_mode"],
        "graph_revision_fingerprint": safe["graph_revision_fingerprint"],
        "graph_content_fingerprint": safe["graph_content_fingerprint"],
        "effective_graph_view_fingerprint": (safe["effective_graph_view_fingerprint"]),
        "source_session_binding_fingerprint": (safe["source_session_binding_fingerprint"]),
        "source_access_fingerprint": safe["source_access_fingerprint"],
        "permission_lineage_fingerprint": (safe["permission_lineage_fingerprint"]),
        "index_fingerprint": safe["index_fingerprint"],
        "tokenizer_profile_fingerprint": (safe["candidate_admission_profile_fingerprint"]),
        "authorized_observation_set_fingerprint": (safe["authorized_observation_set_fingerprint"]),
        "candidate_set_fingerprint": safe["candidate_set_fingerprint"],
        "cache_binding_fingerprint": safe["cache_binding_fingerprint"],
        "relation_projection_base_precompute_fingerprint": (
            safe["relation_projection_base_precompute_fingerprint"]
        ),
        "before_binding_cache_entry_count": before_cache["binding_entry_count"],
        "before_base_cache_entry_count": before_cache["base_entry_count"],
        "after_binding_cache_entry_count": after_cache["binding_entry_count"],
        "after_base_cache_entry_count": after_cache["base_entry_count"],
        "binding_started": binding_phase["started"],
        "binding_completed": binding_phase["completed"],
        "binding_elapsed_ms": binding_phase["elapsed_ms"],
        "binding_invocation_count": binding_phase["invocation_count"],
        "binding_publication_status": binding_phase["publication_status"],
        "base_builder_started": base_builder_phase["started"],
        "base_builder_completed": base_builder_phase["completed"],
        "base_builder_elapsed_ms": base_builder_phase["elapsed_ms"],
        "base_builder_invocation_count": base_builder_phase["invocation_count"],
        "base_publication_status": base_builder_phase["publication_status"],
        **counts,
    }
    if supplied_evidence_fingerprint != sha256_json(fingerprint_payload):
        raise ContractValidationError(
            "relation projection phase-traced owner evidence seal mismatch"
        )
    _assert_no_legacy_identity_fields(safe)
    assert_no_public_raw_references(
        safe,
        "issue56_relation_projection_phase_traced_owner_precompute",
    )
    return safe


def relation_projection_cache_containers_are_isolated(
    before: Issue56DiagnosticComposition,
    after: Issue56DiagnosticComposition,
) -> bool:
    before_snapshot = getattr(
        before.effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        None,
    )
    after_snapshot = getattr(
        after.effective_graph_view,
        _EFFECTIVE_GRAPH_CONTENT_SNAPSHOT_ATTRIBUTE,
        None,
    )
    return before.effective_graph_view is not after.effective_graph_view and (
        before_snapshot is None or after_snapshot is None or before_snapshot is not after_snapshot
    )


def build_safe_relation_projection_equivalence_arm(
    *,
    arm_id: str,
    composition: Issue56DiagnosticComposition,
    prompt: str,
    initialize_response: Mapping[str, Any],
    list_response: Mapping[str, Any],
    query_response: Mapping[str, Any],
    http_elapsed_ms: float,
    cache_before: Mapping[str, Any],
    cache_after: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one safe full-HTTP arm result without embedding private evidence."""

    if arm_id not in {
        "before_cold",
        "after_precomputed",
        "offline_cold_precomputed",
        "preexisting_precomputed",
    }:
        raise ContractValidationError("relation projection equivalence arm is invalid")
    initialized = initialize_response.get("result")
    listed = list_response.get("result")
    query_result = query_response.get("result")
    if not isinstance(initialized, Mapping):
        raise ContractValidationError("relation projection MCP initialize response is invalid")
    if not isinstance(listed, Mapping) or not isinstance(
        listed.get("tools"),
        list,
    ):
        raise ContractValidationError("relation projection MCP tool list is invalid")
    if not isinstance(query_result, Mapping):
        raise ContractValidationError("relation projection MCP query response is invalid")
    structured = query_result.get("structuredContent")
    if not isinstance(structured, Mapping):
        raise ContractValidationError("relation projection MCP structured response is unavailable")
    data = structured.get("data")
    if not isinstance(data, Mapping):
        raise ContractValidationError("relation projection MCP data envelope is unavailable")
    answer = data.get("answer")
    diagnostic = data.get("diagnostic")
    if not isinstance(answer, Mapping) or not isinstance(diagnostic, Mapping):
        raise ContractValidationError("relation projection MCP result bindings are unavailable")
    if diagnostic.get("query_hash") != sha256_json(prompt):
        raise ContractValidationError("relation projection prompt/result binding mismatch")
    listed_names = {str(tool.get("name")) for tool in listed["tools"] if isinstance(tool, Mapping)}
    if ISSUE56_DIAGNOSTIC_TOOL_NAME not in listed_names:
        raise ContractValidationError("relation projection query tool was not advertised")
    semantic = composition.state.last_semantic_equivalence
    phase_trace = composition.state.last_semantic_phase_trace
    if not isinstance(semantic, Mapping) or not isinstance(
        phase_trace,
        Mapping,
    ):
        raise ContractValidationError("relation projection semantic evidence is unavailable")
    relation_events = [
        phase
        for phase in phase_trace.get("phases", ())
        if isinstance(phase, Mapping) and phase.get("phase") == "relation_projection"
    ]
    if len(relation_events) != 1:
        raise ContractValidationError("relation projection phase timing is unavailable")
    relation_event = relation_events[0]
    query_events = [
        phase
        for phase in composition.state.safe_phase_trace()
        if phase["phase"] == "authorized_semantic_mail_session_query"
    ]
    if len(query_events) != 1:
        raise ContractValidationError("relation projection query timing is unavailable")
    graph_path_count = semantic["counts"]["graph_path_count"]
    citation_count = semantic["counts"]["citation_count"]
    citations = data.get("citations")
    graph_hits = data.get("graph_hits")
    completed = (
        structured.get("status") == "ok"
        and data.get("status") == "ok"
        and answer.get("status") == "answered"
        and answer.get("answer_hash") == semantic["answer_hash"]
        and answer.get("source_result_fingerprint") == semantic["source_result_fingerprint"]
        and diagnostic.get("result_fingerprint") == semantic["result_fingerprint"]
        and isinstance(citations, list)
        and sha256_json(citations) == semantic["citation_fingerprint"]
        and isinstance(graph_hits, Mapping)
        and graph_hits.get("count") == graph_path_count
        and phase_trace.get("terminal_status") == "completed"
        and phase_trace.get("deadline_exhausted_phase") is None
        and all(
            isinstance(phase, Mapping) and phase.get("outcome") in {"completed", "skipped"}
            for phase in phase_trace.get("phases", ())
        )
        and relation_event.get("outcome") == "completed"
        and graph_path_count > 0
        and citation_count > 0
        and composition.state.authentication_count == 1
        and composition.state.actor_resolution_count == 1
        and composition.state.authorization_decision_count == 1
        and composition.state.authorization_denial_count == 0
        and composition.state.semantic_handler_count == 1
        and composition.state.hybrid_query_count == 1
    )
    arm = {
        "arm_id": arm_id,
        "status": "passed" if completed else "blocked",
        "cache_role": composition.relation_projection_cache_role,
        "semantic": dict(semantic),
        "cache": {
            "before": dict(cache_before),
            "after": dict(cache_after),
            "entry_delta": (int(cache_after["entry_count"]) - int(cache_before["entry_count"])),
            "binding_snapshot_entry_delta": (
                int(cache_after["binding_snapshot_entry_count"])
                - int(cache_before["binding_snapshot_entry_count"])
            ),
        },
        "counts": {
            "http_request_count": 3,
            "authentication_count": composition.state.authentication_count,
            "policy_denial_count": (composition.state.authorization_denial_count),
            "hybrid_query_count": composition.state.hybrid_query_count,
            "graph_path_count": graph_path_count,
            "citation_count": citation_count,
            "score_count": semantic["counts"]["score_count"],
        },
        "timing": {
            "relation_projection_elapsed_ms": relation_event["elapsed_ms"],
            "query_elapsed_ms": query_events[0]["elapsed_ms"],
            "http_elapsed_ms": round(max(0.0, http_elapsed_ms), 6),
            "semantic_phases": dict(phase_trace),
        },
    }
    _assert_no_legacy_identity_fields(arm)
    assert_no_public_raw_references(
        arm,
        "issue56_relation_projection_equivalence_arm",
    )
    validate_public_gateway_payload(arm)
    return arm


def build_safe_relation_projection_equivalence_report(
    *,
    source: Issue56SealedSourceDiagnosticInput,
    prompt: str,
    before_arm: Mapping[str, Any],
    after_arm: Mapping[str, Any],
    source_loader_elapsed_ms: float,
    consumed_claim_fingerprint: str,
    consumed_claim_byte_sha256: str,
    execution_binding_fingerprint: str,
    cache_containers_isolated: bool,
    graph_content_preseal: Issue56GraphContentPresealEvidence | None = None,
) -> dict[str, Any]:
    """Compare two timing-free semantic projections and publish hash-only proof."""

    if source.diagnostic_mode_id not in _RELATION_PROJECTION_EQUIVALENCE_MODE_IDS:
        raise ContractValidationError("relation projection equivalence report mode mismatch")
    for value, label in (
        (consumed_claim_fingerprint, "consumed claim fingerprint"),
        (consumed_claim_byte_sha256, "consumed claim byte seal"),
        (execution_binding_fingerprint, "execution binding fingerprint"),
    ):
        _require_sha256(value, label)
    if source_loader_elapsed_ms < 0:
        raise ContractValidationError("relation projection source loader timing is invalid")
    v6_mode = source.diagnostic_mode_id in _RELATION_PROJECTION_EQUIVALENCE_V6_MODE_IDS
    if v6_mode and (
        graph_content_preseal is None
        or graph_content_preseal.status != "passed"
        or graph_content_preseal.session_binding_fingerprint
        != source.session.source_session_binding_fingerprint
        or graph_content_preseal.source_access_fingerprint
        != source.session.authorized_source.authorization_fingerprint
        or graph_content_preseal.source_binding_fingerprint != source.source_binding_fingerprint
        or graph_content_preseal.permission_lineage_fingerprint
        != source.permission_lineage_fingerprint
        or graph_content_preseal.effective_graph_view_fingerprint
        != source.effective_graph_view_fingerprint
        or graph_content_preseal.graph_revision_fingerprint != source.graph_revision_fingerprint
        or graph_content_preseal.index_fingerprint != source.session.index.index_fingerprint
        or graph_content_preseal.candidate_admission_profile_fingerprint
        != source.session.index.profile_fingerprint
        or graph_content_preseal.authorized_observation_set_fingerprint
        != source.relation_projection_base_precompute.authorized_observation_set_fingerprint
        or graph_content_preseal.authorized_observation_count != source.observation_count
    ):
        raise ContractValidationError("relation projection graph content preseal binding mismatch")
    if not v6_mode and graph_content_preseal is not None:
        raise ContractValidationError(
            "legacy relation projection diagnostic cannot claim graph content preseal"
        )
    before_semantic = before_arm.get("semantic")
    after_semantic = after_arm.get("semantic")
    if not isinstance(before_semantic, Mapping) or not isinstance(
        after_semantic,
        Mapping,
    ):
        raise ContractValidationError("relation projection semantic comparison is unavailable")
    field_groups = {
        "status": ("status",),
        "answer": (
            "answer_status",
            "answer_hash",
            "source_result_fingerprint",
        ),
        "plan": ("query_hash", "plan_fingerprint"),
        "result": (
            "result_fingerprint",
            "semantic_payload_fingerprint",
        ),
        "paths": ("path_fingerprint",),
        "citations": ("citation_fingerprint",),
        "scores": ("score_fingerprint",),
        "permission": ("permission_fingerprint",),
        "lineage": (
            "lineage_fingerprint",
            "lineage_crosswalk_fingerprint",
        ),
        "runtime": (
            "runtime_method_fingerprint",
            "profile_fingerprint",
            "execution_component_fingerprint",
        ),
        "index": ("index_fingerprint",),
        "graph": ("graph_revision_fingerprint",),
    }
    equivalence = {
        group: all(
            before_semantic.get(field_name) == after_semantic.get(field_name)
            for field_name in field_names
        )
        for group, field_names in field_groups.items()
    }
    equivalence["counts"] = before_semantic.get("counts") == after_semantic.get("counts")
    before_cache = before_arm["cache"]
    after_cache = after_arm["cache"]
    cache_acceptance = {
        "containers_isolated": cache_containers_isolated,
        "before_started_empty": (
            before_cache["before"]["entry_count"] == 0
            and not before_cache["before"]["expected_binding_present"]
            and before_cache["before"]["binding_snapshot_entry_count"] == 0
            and not before_cache["before"]["expected_binding_snapshot_present"]
        ),
        "before_built_one": (
            before_cache["after"]["entry_count"] == 1
            and before_cache["after"]["expected_binding_present"]
            and before_cache["after"]["binding_snapshot_entry_count"] == 1
            and before_cache["after"]["expected_binding_snapshot_present"]
            and before_cache["entry_delta"] == 1
        ),
        "after_started_primed": (
            after_cache["before"]["entry_count"] == 1
            and after_cache["before"]["expected_binding_present"]
            and after_cache["before"]["binding_snapshot_entry_count"] == 1
            and after_cache["before"]["expected_binding_snapshot_present"]
        ),
        "after_reused_primed": (
            after_cache["after"]["entry_count"] == 1
            and after_cache["after"]["expected_binding_present"]
            and after_cache["after"]["binding_snapshot_entry_count"] == 1
            and after_cache["after"]["expected_binding_snapshot_present"]
            and after_cache["entry_delta"] == 0
        ),
        "graph_content_presealed": (
            not v6_mode
            or (
                graph_content_preseal is not None
                and graph_content_preseal.before_binding_cache_entry_count == 0
                and graph_content_preseal.before_base_cache_entry_count == 0
                and graph_content_preseal.after_binding_cache_entry_count == 1
                and graph_content_preseal.after_base_cache_entry_count == 1
            )
        ),
    }
    before_relation_ms = float(before_arm["timing"]["relation_projection_elapsed_ms"])
    after_relation_ms = float(after_arm["timing"]["relation_projection_elapsed_ms"])
    passed = (
        before_arm.get("status") == "passed"
        and after_arm.get("status") == "passed"
        and all(equivalence.values())
        and all(cache_acceptance.values())
        and source.prompt_selection is not None
        and source.prompt_selection.lexical_anchor_count > 0
        and source.prompt_selection.authorized_connected_graph_path_count > 0
        and source.relation_projection_base_precompute.helper_invocation_count == 1
        and (not v6_mode or graph_content_preseal is not None)
    )
    report_artifact_id = (
        "formowl_issue56_relation_projection_equivalence_diagnostic_v2"
        if v6_mode
        else "formowl_issue56_relation_projection_equivalence_diagnostic_v1"
    )
    report = {
        "artifact_id": report_artifact_id,
        "schema_version": 2 if v6_mode else 1,
        "diagnostic_mode_id": source.diagnostic_mode_id,
        "status": "passed" if passed else "blocked",
        "claim_status": ISSUE56_DIAGNOSTIC_CLAIM_STATUS,
        "quality_claim": "not_made",
        "diagnostic_only": True,
        "methodology_authority_status": "blocked",
        "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        "identity_scope_fingerprint": sha256_json(
            {
                "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
                "workspace_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
                "approver_user_id": ISSUE56_DIAGNOSTIC_USER_ID,
            }
        ),
        "source_fixture_mode": ("sealed_source_real_prompt_relation_projection_equivalence"),
        "sealed_source_asset": "validated_and_exercised",
        "external_google_oauth_exchange": "not_exercised",
        "production_connected_tool_policy": "not_exercised",
        "real_llm": "not_exercised",
        "prompt_hash": sha256_json(prompt),
        "source_prompt_selection": (
            source.prompt_selection.to_safe_dict()
            if source.prompt_selection is not None
            else {"status": "blocked"}
        ),
        "source_binding": {
            "source_asset_fingerprint": source.source_asset_fingerprint,
            "loader_contract_fingerprint": source.loader_contract_fingerprint,
            "observation_inventory_fingerprint": (source.observation_inventory_fingerprint),
            "permission_lineage_fingerprint": (source.permission_lineage_fingerprint),
            "effective_graph_view_fingerprint": (source.effective_graph_view_fingerprint),
            "graph_revision_fingerprint": source.graph_revision_fingerprint,
            "source_loader_binding_fingerprint": (source.source_loader_binding_fingerprint),
            "source_binding_fingerprint": source.source_binding_fingerprint,
        },
        "version_guard": {
            "status": "consumed_once",
            "consumed_claim_fingerprint": consumed_claim_fingerprint,
            "consumed_claim_byte_sha256": consumed_claim_byte_sha256,
            "execution_binding_fingerprint": execution_binding_fingerprint,
        },
        "graph_content_preseal": (
            graph_content_preseal.to_safe_dict()
            if graph_content_preseal is not None
            else {"status": "not_exercised"}
        ),
        "equivalence": equivalence,
        "cache_acceptance": cache_acceptance,
        "counts": {
            "arm_count": 2,
            "source_observation_count": source.observation_count,
            "owner_relation_base_precompute_count": (
                source.relation_projection_base_precompute.helper_invocation_count
            ),
            "before_relation_base_build_count": (before_cache["entry_delta"]),
            "after_relation_base_build_count": after_cache["entry_delta"],
            "before_relation_binding_build_count": (
                before_cache["after"]["binding_snapshot_entry_count"]
                - before_cache["before"]["binding_snapshot_entry_count"]
            ),
            "after_relation_binding_build_count": (
                after_cache["after"]["binding_snapshot_entry_count"]
                - after_cache["before"]["binding_snapshot_entry_count"]
            ),
            "before_graph_path_count": (before_arm["counts"]["graph_path_count"]),
            "after_graph_path_count": (after_arm["counts"]["graph_path_count"]),
            "before_citation_count": before_arm["counts"]["citation_count"],
            "after_citation_count": after_arm["counts"]["citation_count"],
        },
        "timing": {
            "source_loader_elapsed_ms": round(
                source_loader_elapsed_ms,
                6,
            ),
            "relation_projection_base_precompute_elapsed_ms": (
                source.relation_projection_base_precompute.elapsed_ms
            ),
            "before_graph_content_preseal_elapsed_ms": (
                graph_content_preseal.before_preseal_elapsed_ms
                if graph_content_preseal is not None
                else None
            ),
            "after_graph_snapshot_validation_elapsed_ms": (
                graph_content_preseal.after_snapshot_validation_elapsed_ms
                if graph_content_preseal is not None
                else None
            ),
            "before_relation_projection_elapsed_ms": before_relation_ms,
            "after_relation_projection_elapsed_ms": after_relation_ms,
            "relation_projection_delta_ms": round(
                before_relation_ms - after_relation_ms,
                6,
            ),
            "relation_projection_after_to_before_ratio": (
                round(after_relation_ms / before_relation_ms, 6) if before_relation_ms > 0 else None
            ),
            "improvement_observed": after_relation_ms < before_relation_ms,
            "latency_claim": "measurement_only_not_quality_claim",
            "before_query_elapsed_ms": (before_arm["timing"]["query_elapsed_ms"]),
            "after_query_elapsed_ms": (after_arm["timing"]["query_elapsed_ms"]),
            "before_http_elapsed_ms": (before_arm["timing"]["http_elapsed_ms"]),
            "after_http_elapsed_ms": after_arm["timing"]["http_elapsed_ms"],
            "before_semantic_phases": (before_arm["timing"]["semantic_phases"]),
            "after_semantic_phases": (after_arm["timing"]["semantic_phases"]),
        },
        "arms": {
            "before_cold": dict(before_arm),
            "after_precomputed": dict(after_arm),
        },
        "boundary_status": {
            "full_asgi_mcp_each_arm": (
                "passed"
                if before_arm.get("status") == after_arm.get("status") == "passed"
                else "blocked"
            ),
            "timing_free_semantic_equivalence": (
                "passed" if all(equivalence.values()) else "blocked"
            ),
            "relation_projection_cache_isolation": (
                "passed" if all(cache_acceptance.values()) else "blocked"
            ),
            "graph_content_preseal": (
                "passed"
                if graph_content_preseal is not None and graph_content_preseal.status == "passed"
                else "not_exercised"
                if not v6_mode
                else "blocked"
            ),
            "exactly_once_version_guard": "passed",
            "quality_uat": "not_executed",
            "independent_holdout": "not_executed",
            "transfer_evaluation": "not_executed",
        },
    }
    report["safe_trace_binding_fingerprint"] = sha256_json(
        {
            "diagnostic_mode_id": source.diagnostic_mode_id,
            "prompt_hash": report["prompt_hash"],
            "source_binding_fingerprint": source.source_binding_fingerprint,
            "execution_binding_fingerprint": execution_binding_fingerprint,
            "before_semantic": before_semantic,
            "after_semantic": after_semantic,
            "before_phase_trace": before_arm["timing"]["semantic_phases"],
            "after_phase_trace": after_arm["timing"]["semantic_phases"],
            "equivalence": equivalence,
            "cache_acceptance": cache_acceptance,
            "graph_content_preseal_fingerprint": (
                graph_content_preseal.evidence_binding_fingerprint
                if graph_content_preseal is not None
                else None
            ),
        }
    )
    _assert_no_legacy_identity_fields(report)
    assert_no_public_raw_references(
        report,
        report_artifact_id,
    )
    validate_public_gateway_payload(report)
    return report


def build_safe_relation_projection_offline_equivalence_v7_report(
    *,
    source: Issue56SealedSourceDiagnosticInput,
    prompt: str,
    cold_arm: Mapping[str, Any],
    after_arm: Mapping[str, Any],
    source_loader_elapsed_ms: float,
    consumed_claim_fingerprint: str,
    consumed_claim_byte_sha256: str,
    execution_binding_fingerprint: str,
    cache_containers_isolated: bool,
    preflight: Issue56OfflineEquivalencePreflightEvidence,
    offline_precompute: Issue56OfflineRelationPrecomputeEvidence,
) -> dict[str, Any]:
    """Publish the v7 timing-free real-source equivalence result."""

    if source.diagnostic_mode_id not in _RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_MODE_IDS:
        raise ContractValidationError(
            "relation projection offline equivalence report mode mismatch"
        )
    for value, label in (
        (consumed_claim_fingerprint, "consumed claim fingerprint"),
        (consumed_claim_byte_sha256, "consumed claim byte seal"),
        (execution_binding_fingerprint, "execution binding fingerprint"),
    ):
        _require_sha256(value, label)
    if source_loader_elapsed_ms < 0:
        raise ContractValidationError("relation projection offline source loader timing is invalid")
    if (
        preflight.status != "passed"
        or preflight.source_binding_fingerprint != source.source_binding_fingerprint
        or preflight.permission_lineage_fingerprint != source.permission_lineage_fingerprint
        or preflight.effective_graph_view_fingerprint != source.effective_graph_view_fingerprint
        or preflight.graph_revision_fingerprint != source.graph_revision_fingerprint
        or preflight.index_fingerprint != source.session.index.index_fingerprint
        or preflight.candidate_admission_profile_fingerprint
        != source.session.index.profile_fingerprint
        or preflight.authorized_observation_set_fingerprint
        != source.relation_projection_base_precompute.authorized_observation_set_fingerprint
        or preflight.cold_binding_cache_entry_count != 0
        or preflight.cold_base_cache_entry_count != 0
        or preflight.after_binding_cache_entry_count != 1
        or preflight.after_base_cache_entry_count != 1
        or offline_precompute.status != "passed"
        or offline_precompute.cache_status != "primed_from_cold"
        or offline_precompute.helper_invocation_count != 1
        or offline_precompute.query_executed
        or offline_precompute.binding_snapshot_status != "completed"
        or offline_precompute.base_builder_status != "completed"
        or offline_precompute.binding_entry_count_before != 0
        or offline_precompute.binding_entry_count_after != 1
        or offline_precompute.base_entry_count_before != 0
        or offline_precompute.base_entry_count_after != 1
        or offline_precompute.cache_binding_fingerprint
        != source.relation_projection_base_precompute.cache_binding_fingerprint
        or offline_precompute.precompute_fingerprint
        != source.relation_projection_base_precompute.precompute_fingerprint
        or offline_precompute.graph_revision_fingerprint != source.graph_revision_fingerprint
        or offline_precompute.effective_graph_view_fingerprint
        != source.effective_graph_view_fingerprint
        or offline_precompute.index_fingerprint != source.session.index.index_fingerprint
        or offline_precompute.candidate_admission_profile_fingerprint
        != source.session.index.profile_fingerprint
        or offline_precompute.authorized_observation_set_fingerprint
        != source.relation_projection_base_precompute.authorized_observation_set_fingerprint
        or offline_precompute.candidate_set_fingerprint
        != source.relation_projection_base_precompute.candidate_set_fingerprint
    ):
        raise ContractValidationError(
            "relation projection offline equivalence evidence binding mismatch"
        )

    cold_semantic = cold_arm.get("semantic")
    after_semantic = after_arm.get("semantic")
    if not isinstance(cold_semantic, Mapping) or not isinstance(
        after_semantic,
        Mapping,
    ):
        raise ContractValidationError(
            "relation projection offline semantic comparison is unavailable"
        )
    field_groups = {
        "status": ("status",),
        "answer": (
            "answer_status",
            "answer_hash",
            "source_result_fingerprint",
        ),
        "plan": ("query_hash", "plan_fingerprint"),
        "result": (
            "result_fingerprint",
            "semantic_payload_fingerprint",
        ),
        "paths": ("path_fingerprint",),
        "citations": ("citation_fingerprint",),
        "scores": ("score_fingerprint",),
        "permission": ("permission_fingerprint",),
        "lineage": (
            "lineage_fingerprint",
            "lineage_crosswalk_fingerprint",
        ),
        "runtime": (
            "runtime_method_fingerprint",
            "profile_fingerprint",
            "execution_component_fingerprint",
        ),
        "index": ("index_fingerprint",),
        "graph": ("graph_revision_fingerprint",),
    }
    equivalence = {
        group: all(
            cold_semantic.get(field_name) == after_semantic.get(field_name)
            for field_name in field_names
        )
        for group, field_names in field_groups.items()
    }
    equivalence["counts"] = cold_semantic.get("counts") == after_semantic.get("counts")
    cold_cache = cold_arm["cache"]
    after_cache = after_arm["cache"]
    cache_acceptance = {
        "containers_isolated": cache_containers_isolated,
        "preflight_cold_0_0_after_1_1": (
            preflight.cold_binding_cache_entry_count == 0
            and preflight.cold_base_cache_entry_count == 0
            and preflight.after_binding_cache_entry_count == 1
            and preflight.after_base_cache_entry_count == 1
        ),
        "offline_cold_0_0_to_1_1": (
            offline_precompute.binding_entry_count_before == 0
            and offline_precompute.base_entry_count_before == 0
            and offline_precompute.binding_entry_count_after == 1
            and offline_precompute.base_entry_count_after == 1
        ),
        "cold_query_reused_1_1": _relation_projection_query_reused_cache(cold_cache),
        "after_query_reused_1_1": _relation_projection_query_reused_cache(after_cache),
    }
    prompt_selection = source.prompt_selection
    passed = (
        cold_arm.get("status") == "passed"
        and after_arm.get("status") == "passed"
        and all(equivalence.values())
        and all(cache_acceptance.values())
        and prompt_selection is not None
        and prompt_selection.lexical_anchor_count > 0
        and prompt_selection.authorized_connected_graph_path_count > 0
        and int(cold_arm["counts"]["graph_path_count"]) > 0
        and int(after_arm["counts"]["graph_path_count"]) > 0
        and int(cold_arm["counts"]["citation_count"]) > 0
        and int(after_arm["counts"]["citation_count"]) > 0
        and cold_arm["timing"]["semantic_phases"]["deadline_exhausted_phase"] is None
        and after_arm["timing"]["semantic_phases"]["deadline_exhausted_phase"] is None
    )
    report = {
        "artifact_id": ("formowl_issue56_relation_projection_offline_equivalence_diagnostic_v1"),
        "schema_version": 1,
        "diagnostic_mode_id": source.diagnostic_mode_id,
        "status": "passed" if passed else "blocked",
        "claim_status": ISSUE56_DIAGNOSTIC_CLAIM_STATUS,
        "quality_claim": "not_made",
        "diagnostic_only": True,
        "methodology_authority_status": "blocked",
        "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        "identity_scope_fingerprint": sha256_json(
            {
                "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
                "workspace_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
                "approver_user_id": ISSUE56_DIAGNOSTIC_USER_ID,
            }
        ),
        "source_fixture_mode": (
            "sealed_source_real_prompt_relation_projection_offline_equivalence"
        ),
        "sealed_source_asset": "validated_and_exercised",
        "external_google_oauth_exchange": "not_exercised",
        "production_connected_tool_policy": "not_exercised",
        "real_llm": "not_exercised",
        "prompt_hash": sha256_json(prompt),
        "source_prompt_selection": (
            prompt_selection.to_safe_dict()
            if prompt_selection is not None
            else {"status": "blocked"}
        ),
        "source_binding": {
            "source_asset_fingerprint": source.source_asset_fingerprint,
            "loader_contract_fingerprint": source.loader_contract_fingerprint,
            "observation_inventory_fingerprint": (source.observation_inventory_fingerprint),
            "permission_lineage_fingerprint": (source.permission_lineage_fingerprint),
            "effective_graph_view_fingerprint": (source.effective_graph_view_fingerprint),
            "graph_revision_fingerprint": source.graph_revision_fingerprint,
            "source_loader_binding_fingerprint": (source.source_loader_binding_fingerprint),
            "source_binding_fingerprint": source.source_binding_fingerprint,
        },
        "version_guard": {
            "status": "consumed_once",
            "consumed_claim_fingerprint": consumed_claim_fingerprint,
            "consumed_claim_byte_sha256": consumed_claim_byte_sha256,
            "execution_binding_fingerprint": execution_binding_fingerprint,
        },
        "query_budget": {
            "per_arm_ms": 1500,
            "offline_precompute_consumes_query_budget": False,
            "phase_local_budget_override": False,
        },
        "preflight": preflight.to_safe_dict(),
        "offline_precompute": offline_precompute.to_safe_dict(),
        "equivalence": equivalence,
        "cache_acceptance": cache_acceptance,
        "counts": {
            "arm_count": 2,
            "source_observation_count": source.observation_count,
            "graph_preseal_helper_invocation_count": (
                preflight.graph_preseal_helper_invocation_count
            ),
            "after_relation_precompute_helper_invocation_count": (
                preflight.after_relation_precompute_helper_invocation_count
            ),
            "cold_offline_precompute_helper_invocation_count": (
                offline_precompute.helper_invocation_count
            ),
            "cold_graph_path_count": cold_arm["counts"]["graph_path_count"],
            "after_graph_path_count": after_arm["counts"]["graph_path_count"],
            "cold_citation_count": cold_arm["counts"]["citation_count"],
            "after_citation_count": after_arm["counts"]["citation_count"],
        },
        "timing": {
            "source_loader_elapsed_ms": round(source_loader_elapsed_ms, 6),
            "cold_graph_preseal_elapsed_ms": (preflight.cold_graph_preseal_elapsed_ms),
            "after_graph_preseal_elapsed_ms": (preflight.after_graph_preseal_elapsed_ms),
            "after_relation_precompute_elapsed_ms": (
                preflight.after_relation_precompute_elapsed_ms
            ),
            "cold_offline_precompute_total_elapsed_ms": (offline_precompute.total_elapsed_ms),
            "cold_offline_binding_elapsed_ms": (offline_precompute.binding_snapshot_elapsed_ms),
            "cold_offline_base_builder_elapsed_ms": (offline_precompute.base_builder_elapsed_ms),
            "cold_relation_projection_elapsed_ms": (
                cold_arm["timing"]["relation_projection_elapsed_ms"]
            ),
            "after_relation_projection_elapsed_ms": (
                after_arm["timing"]["relation_projection_elapsed_ms"]
            ),
            "cold_query_elapsed_ms": cold_arm["timing"]["query_elapsed_ms"],
            "after_query_elapsed_ms": after_arm["timing"]["query_elapsed_ms"],
            "cold_http_elapsed_ms": cold_arm["timing"]["http_elapsed_ms"],
            "after_http_elapsed_ms": after_arm["timing"]["http_elapsed_ms"],
            "cold_semantic_phases": cold_arm["timing"]["semantic_phases"],
            "after_semantic_phases": after_arm["timing"]["semantic_phases"],
            "latency_claim": "measurement_only_not_quality_claim",
        },
        "arms": {
            "offline_cold_precomputed": dict(cold_arm),
            "preexisting_precomputed": dict(after_arm),
        },
        "boundary_status": {
            "non_query_preflight_before_claim": "passed",
            "offline_unbudgeted_precompute_after_claim": (
                "passed" if offline_precompute.status == "passed" else "blocked"
            ),
            "normal_1500ms_asgi_mcp_each_arm": (
                "passed"
                if cold_arm.get("status") == after_arm.get("status") == "passed"
                else "blocked"
            ),
            "timing_free_semantic_equivalence": (
                "passed" if all(equivalence.values()) else "blocked"
            ),
            "relation_projection_cache_isolation": (
                "passed" if all(cache_acceptance.values()) else "blocked"
            ),
            "exactly_once_version_guard": "passed",
            "quality_uat": "not_executed",
            "independent_holdout": "not_executed",
            "transfer_evaluation": "not_executed",
        },
    }
    report["safe_trace_binding_fingerprint"] = sha256_json(
        {
            "diagnostic_mode_id": source.diagnostic_mode_id,
            "prompt_hash": report["prompt_hash"],
            "source_binding_fingerprint": source.source_binding_fingerprint,
            "execution_binding_fingerprint": execution_binding_fingerprint,
            "preflight_fingerprint": preflight.evidence_binding_fingerprint,
            "offline_precompute_fingerprint": (offline_precompute.evidence_binding_fingerprint),
            "cold_semantic": cold_semantic,
            "after_semantic": after_semantic,
            "cold_phase_trace": cold_arm["timing"]["semantic_phases"],
            "after_phase_trace": after_arm["timing"]["semantic_phases"],
            "equivalence": equivalence,
            "cache_acceptance": cache_acceptance,
        }
    )
    _assert_no_legacy_identity_fields(report)
    assert_no_public_raw_references(
        report,
        "formowl_issue56_relation_projection_offline_equivalence_diagnostic_v1",
    )
    validate_public_gateway_payload(report)
    return report


def _relation_projection_query_reused_cache(
    cache: Mapping[str, Any],
) -> bool:
    before = cache.get("before")
    after = cache.get("after")
    return (
        isinstance(before, Mapping)
        and isinstance(after, Mapping)
        and before.get("binding_snapshot_entry_count") == 1
        and before.get("entry_count") == 1
        and before.get("expected_binding_snapshot_present") is True
        and before.get("expected_binding_present") is True
        and before.get("snapshot_graph_binding_status") == "passed"
        and after.get("binding_snapshot_entry_count") == 1
        and after.get("entry_count") == 1
        and after.get("expected_binding_snapshot_present") is True
        and after.get("expected_binding_present") is True
        and after.get("snapshot_graph_binding_status") == "passed"
        and cache.get("binding_snapshot_entry_delta") == 0
        and cache.get("entry_delta") == 0
    )


def mcp_initialize_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "issue56_diagnostic_initialize",
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "formowl-issue56-prompt-diagnostic",
                "version": "1.0",
            },
        },
    }


def mcp_list_tools_request() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "issue56_diagnostic_list",
        "method": "tools/list",
    }


def mcp_query_request(prompt: str) -> dict[str, Any]:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ContractValidationError("diagnostic prompt is required")
    return {
        "jsonrpc": "2.0",
        "id": "issue56_diagnostic_query",
        "method": "tools/call",
        "params": {
            "name": ISSUE56_DIAGNOSTIC_TOOL_NAME,
            "arguments": {"query_text": prompt},
        },
    }


def mcp_headers(*, bearer: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_PROTOCOL_VERSION,
    }
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


def build_safe_diagnostic_report(
    *,
    composition: Issue56DiagnosticComposition,
    prompt: str,
    initialize_response: Mapping[str, Any],
    list_response: Mapping[str, Any],
    query_response: Mapping[str, Any],
    http_elapsed_ms: float,
    source_loader_elapsed_ms: float | None = None,
    consumed_claim_fingerprint: str | None = None,
    consumed_claim_byte_sha256: str | None = None,
    execution_binding_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Build one hash/status/count/timing-only public diagnostic report."""

    initialized = initialize_response.get("result")
    listed = list_response.get("result")
    query_result = query_response.get("result")
    if not isinstance(initialized, Mapping):
        raise ContractValidationError("diagnostic MCP initialize response is invalid")
    if not isinstance(listed, Mapping) or not isinstance(listed.get("tools"), list):
        raise ContractValidationError("diagnostic MCP tool list is invalid")
    if not isinstance(query_result, Mapping):
        raise ContractValidationError("diagnostic MCP query response is invalid")
    structured = query_result.get("structuredContent")
    if not isinstance(structured, Mapping):
        raise ContractValidationError("diagnostic MCP structured response is unavailable")
    data = structured.get("data")
    if not isinstance(data, Mapping):
        raise ContractValidationError("diagnostic MCP data envelope is unavailable")
    diagnostic = data.get("diagnostic")
    answer = data.get("answer")
    if not isinstance(diagnostic, Mapping) or not isinstance(answer, Mapping):
        raise ContractValidationError("diagnostic result bindings are unavailable")
    listed_names = sorted(
        str(tool.get("name")) for tool in listed["tools"] if isinstance(tool, Mapping)
    )
    if ISSUE56_DIAGNOSTIC_TOOL_NAME not in listed_names:
        raise ContractValidationError("diagnostic query tool was not advertised")
    prompt_hash = sha256_json(prompt)
    if diagnostic.get("query_hash") != prompt_hash:
        raise ContractValidationError("diagnostic prompt/result binding mismatch")
    citation_count = answer.get("citation_count")
    graph_path_count = (
        data.get("graph_hits", {}).get("count")
        if isinstance(data.get("graph_hits"), Mapping)
        else None
    )
    state = composition.state
    sealed_mode = composition.diagnostic_mode_id in {
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }
    real_prompt_mode = composition.diagnostic_mode_id in _REAL_PROMPT_DIAGNOSTIC_MODE_IDS
    semantic_trace_completed = (
        isinstance(state.last_semantic_phase_trace, Mapping)
        and state.last_semantic_phase_trace.get("terminal_status") == "completed"
        and all(
            isinstance(phase, Mapping) and phase.get("outcome") in {"completed", "skipped"}
            for phase in state.last_semantic_phase_trace.get("phases", ())
        )
    )
    selection_acceptance_passed = not real_prompt_mode or (
        composition.prompt_selection is not None
        and composition.prompt_selection.prompt_hash == prompt_hash
        and composition.prompt_selection.lexical_anchor_count > 0
        and composition.prompt_selection.authorized_connected_graph_path_count > 0
    )
    passed = (
        structured.get("status") == "ok"
        and data.get("status") == "ok"
        and answer.get("status") == "answered"
        and isinstance(citation_count, int)
        and citation_count > 0
        and isinstance(graph_path_count, int)
        and graph_path_count > 0
        and diagnostic.get("runtime_method_fingerprint")
        == ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT
        and (not real_prompt_mode or semantic_trace_completed)
        and selection_acceptance_passed
        and (
            not sealed_mode
            or (
                state.lineage_crosswalk_precompute_count == 1
                and state.lineage_crosswalk_cache_hit_status == "passed"
                and state.lineage_crosswalk_query_binding_status == "passed"
                and state.relation_projection_base_precompute_count == 1
                and state.relation_projection_base_cache_status == "primed"
            )
        )
    )
    if sealed_mode:
        _require_sha256(
            consumed_claim_fingerprint or "",
            "sealed diagnostic consumed claim fingerprint",
        )
        _require_sha256(
            consumed_claim_byte_sha256 or "",
            "sealed diagnostic consumed claim byte seal",
        )
        _require_sha256(
            execution_binding_fingerprint or "",
            "sealed diagnostic execution binding fingerprint",
        )
        if source_loader_elapsed_ms is None or source_loader_elapsed_ms < 0:
            raise ContractValidationError("sealed diagnostic source loader timing is invalid")
    elif any(
        value is not None
        for value in (
            consumed_claim_fingerprint,
            consumed_claim_byte_sha256,
            execution_binding_fingerprint,
            source_loader_elapsed_ms,
        )
    ):
        raise ContractValidationError("synthetic diagnostic cannot claim sealed execution bindings")
    report = {
        "artifact_id": ISSUE56_DIAGNOSTIC_ARTIFACT_ID,
        "schema_version": ISSUE56_DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_mode_id": composition.diagnostic_mode_id,
        "status": "passed" if passed else "blocked",
        "claim_status": ISSUE56_DIAGNOSTIC_CLAIM_STATUS,
        "quality_claim": "not_made",
        "diagnostic_only": True,
        "methodology_authority_status": "blocked",
        "source_fixture_mode": composition.source_fixture_mode,
        "sealed_source_asset": composition.sealed_source_asset_status,
        "external_google_oauth_exchange": "not_exercised",
        "production_connected_tool_policy": "not_exercised",
        "real_llm": "not_exercised",
        "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
        "identity_scope_fingerprint": sha256_json(
            {
                "identity_scope_mode": ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE,
                "workspace_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
                "approver_user_id": ISSUE56_DIAGNOSTIC_USER_ID,
            }
        ),
        "principal_fingerprint": sha256_json(composition.bridge.principal.to_dict()),
        "prompt_hash": prompt_hash,
        "source_prompt_selection": (
            composition.prompt_selection.to_safe_dict()
            if composition.prompt_selection is not None
            else {"status": "not_exercised"}
        ),
        "response_fingerprint": sha256_json(dict(structured)),
        "runtime_method_fingerprint": diagnostic.get("runtime_method_fingerprint"),
        "result_fingerprint": diagnostic.get("result_fingerprint"),
        "answer_hash": answer.get("answer_hash"),
        "source_binding": (
            {
                "source_asset_fingerprint": composition.source_asset_fingerprint,
                "loader_contract_fingerprint": (composition.loader_contract_fingerprint),
                "observation_inventory_fingerprint": (
                    composition.observation_inventory_fingerprint
                ),
                "permission_lineage_fingerprint": (composition.permission_lineage_fingerprint),
                "effective_graph_view_fingerprint": (composition.effective_graph_view_fingerprint),
                "graph_revision_fingerprint": composition.graph_revision_fingerprint,
                "source_loader_binding_fingerprint": (
                    composition.source_loader_binding_fingerprint
                ),
                "source_binding_fingerprint": (composition.source_binding_fingerprint),
            }
            if sealed_mode
            else {"status": "not_applicable"}
        ),
        "version_guard": (
            {
                "status": "consumed_once",
                "consumed_claim_fingerprint": consumed_claim_fingerprint,
                "consumed_claim_byte_sha256": consumed_claim_byte_sha256,
                "execution_binding_fingerprint": execution_binding_fingerprint,
            }
            if sealed_mode
            else {"status": "not_applicable"}
        ),
        "counts": {
            "http_request_count": 3,
            "advertised_tool_count": len(listed_names),
            "authentication_count": state.authentication_count,
            "actor_resolution_count": state.actor_resolution_count,
            "policy_audit_count": state.authorization_decision_count,
            "policy_denial_count": state.authorization_denial_count,
            "semantic_handler_count": state.semantic_handler_count,
            "hybrid_query_count": state.hybrid_query_count,
            "answer_render_count": state.answer_render_count,
            "citation_count": citation_count,
            "graph_path_count": graph_path_count,
            "source_observation_count": composition.source_observation_count,
            "lexical_anchor_count": (
                composition.prompt_selection.lexical_anchor_count
                if composition.prompt_selection is not None
                else 0
            ),
            "source_selected_connected_path_count": (
                composition.prompt_selection.authorized_connected_graph_path_count
                if composition.prompt_selection is not None
                else 0
            ),
            "lineage_crosswalk_precompute_count": (state.lineage_crosswalk_precompute_count),
            "relation_projection_base_precompute_count": (
                state.relation_projection_base_precompute_count
            ),
        },
        "lineage_crosswalk_precompute": (
            composition.lineage_crosswalk_precompute.to_safe_dict()
            if composition.lineage_crosswalk_precompute is not None
            else {"status": "not_exercised"}
        ),
        "lineage_crosswalk_query": {
            "cache_hit_status": state.lineage_crosswalk_cache_hit_status,
            "query_binding_status": state.lineage_crosswalk_query_binding_status,
        },
        "relation_projection_base_precompute": (
            composition.relation_projection_base_precompute.to_safe_dict()
            if composition.relation_projection_base_precompute is not None
            else {"status": "not_exercised"}
        ),
        "relation_projection_query": {
            "prequery_cache_status": (
                state.relation_projection_base_cache_status if sealed_mode else "not_exercised"
            ),
            "timing_source": (
                "semantic_phase_trace_relation_projection" if sealed_mode else "not_exercised"
            ),
        },
        "timing": {
            "http_total_elapsed_ms": round(max(0.0, http_elapsed_ms), 6),
            "source_loader_elapsed_ms": (
                round(source_loader_elapsed_ms, 6) if source_loader_elapsed_ms is not None else None
            ),
            "lineage_crosswalk_precompute_elapsed_ms": (
                state.lineage_crosswalk_precompute_elapsed_ms
            ),
            "relation_projection_base_precompute_elapsed_ms": (
                state.relation_projection_base_precompute_elapsed_ms
            ),
            "boundary_phases": state.safe_phase_trace(),
            "semantic_phases": state.last_semantic_phase_trace,
        },
        "boundary_status": {
            "http_mcp": "passed",
            "bearer_authentication": ("passed" if state.authentication_count == 1 else "blocked"),
            "synthetic_preverified_principal": (
                "passed" if state.actor_resolution_count == 1 else "blocked"
            ),
            "dispatcher_actor_injection": (
                "passed"
                if (
                    state.handler_requester_user_id == ISSUE56_DIAGNOSTIC_USER_ID
                    and state.handler_workspace_id == ISSUE56_DIAGNOSTIC_WORKSPACE_ID
                    and state.handler_session_id == _TOKEN_SESSION_ID
                )
                else "blocked"
            ),
            "semantic_gateway": ("passed" if state.semantic_handler_count == 1 else "blocked"),
            "hybrid_session": ("passed" if state.hybrid_query_count == 1 else "blocked"),
            "safe_cited_response": "passed" if passed else "blocked",
            "source_backed_prompt_selection": (
                "passed"
                if real_prompt_mode and selection_acceptance_passed
                else "not_exercised"
                if not real_prompt_mode
                else "blocked"
            ),
            "semantic_phase_completion": (
                "passed"
                if real_prompt_mode and semantic_trace_completed
                else "not_exercised"
                if not real_prompt_mode
                else "blocked"
            ),
            "sealed_source_loader": "passed" if sealed_mode else "not_exercised",
            "lineage_crosswalk_precompute": (
                "passed"
                if sealed_mode and state.lineage_crosswalk_precompute_count == 1
                else "not_exercised"
                if not sealed_mode
                else "blocked"
            ),
            "lineage_crosswalk_cache_hit": (
                state.lineage_crosswalk_cache_hit_status if sealed_mode else "not_exercised"
            ),
            "relation_projection_base_precompute": (
                "passed"
                if (
                    sealed_mode
                    and state.relation_projection_base_precompute_count == 1
                    and state.relation_projection_base_cache_status == "primed"
                )
                else "not_exercised"
                if not sealed_mode
                else "blocked"
            ),
            "exactly_once_version_guard": ("passed" if sealed_mode else "not_applicable"),
            "browser_ui": "not_exercised",
            "production_store": "not_exercised",
            "quality_uat": "not_executed",
            "independent_holdout": "not_executed",
            "transfer_evaluation": "not_executed",
        },
    }
    report["safe_trace_binding_fingerprint"] = sha256_json(
        {
            "diagnostic_mode_id": composition.diagnostic_mode_id,
            "prompt_hash": prompt_hash,
            "source_binding_fingerprint": composition.source_binding_fingerprint,
            "lineage_crosswalk_precompute_fingerprint": (
                composition.lineage_crosswalk_precompute.evidence_binding_fingerprint
                if composition.lineage_crosswalk_precompute is not None
                else None
            ),
            "relation_projection_base_precompute_fingerprint": (
                composition.relation_projection_base_precompute.evidence_binding_fingerprint
                if composition.relation_projection_base_precompute is not None
                else None
            ),
            "prompt_selection_proof_fingerprint": (
                composition.prompt_selection.selection_proof_fingerprint
                if composition.prompt_selection is not None
                else None
            ),
            "result_fingerprint": diagnostic.get("result_fingerprint"),
            "semantic_phase_trace": state.last_semantic_phase_trace,
            "boundary_phase_trace": state.safe_phase_trace(),
        }
    )
    _assert_no_legacy_identity_fields(report)
    assert_no_public_raw_references(report, ISSUE56_DIAGNOSTIC_ARTIFACT_ID)
    validate_public_gateway_payload(report)
    return report


def safe_blocked_report(
    reason_code: str,
    *,
    diagnostic_mode_id: str = ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
    version_consumed: bool = False,
) -> dict[str, Any]:
    if diagnostic_mode_id not in {
        ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }:
        diagnostic_mode_id = ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
    sealed_mode = diagnostic_mode_id in {
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID,
        ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_TEST_MODE_ID,
        _ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_TEST_MODE_ID,
    }
    report = {
        "artifact_id": ISSUE56_DIAGNOSTIC_ARTIFACT_ID,
        "schema_version": ISSUE56_DIAGNOSTIC_SCHEMA_VERSION,
        "diagnostic_mode_id": diagnostic_mode_id,
        "status": "blocked",
        "claim_status": ISSUE56_DIAGNOSTIC_CLAIM_STATUS,
        "quality_claim": "not_made",
        "diagnostic_only": True,
        "methodology_authority_status": "blocked",
        "source_fixture_mode": ("sealed_source" if sealed_mode else "synthetic_non_sealed"),
        "sealed_source_asset": (
            "blocked_before_safe_completion" if sealed_mode else "not_exercised"
        ),
        "external_google_oauth_exchange": "not_exercised",
        "production_connected_tool_policy": "not_exercised",
        "real_llm": "not_exercised",
        "version_guard_status": ("consumed" if version_consumed else "not_consumed"),
        "reason_hash": sha256_json(reason_code),
        "counts": {"hybrid_query_count": 0},
    }
    _assert_no_legacy_identity_fields(report)
    assert_no_public_raw_references(report, ISSUE56_DIAGNOSTIC_ARTIFACT_ID)
    return report


def _build_synthetic_semantic_fixture() -> (
    tuple[
        AuthorizedSemanticMailSession,
        EffectiveGraphView,
    ]
):
    observations = _synthetic_observations()
    bundle = build_mail_evidence_bundle(
        observations,
        workspace_id=ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
        owner_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
        source_asset_id="asset_issue56_prompt_mcp_synthetic",
        archive_sha256=sha256_json("issue56_prompt_mcp_synthetic_archive"),
        producer_type="server_side_parser",
        parser_name="issue56_prompt_mcp_synthetic_fixture",
        parser_version="v1",
        upload_session_id="upload_issue56_prompt_mcp_synthetic",
        created_at=_CREATED_AT,
        started_at=_CREATED_AT,
        completed_at=_CREATED_AT,
    )
    observations_by_bundle_id = {
        bundle.mail_evidence_bundle_id: observations,
    }
    session = build_authorized_semantic_mail_session(
        observations_by_bundle_id=observations_by_bundle_id,
        bundles=(bundle,),
        requester_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
        workspace_id=ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    )
    first_body = _observation_by_id(
        observations,
        "obs_issue56_prompt_mcp_body_1",
    )
    second_body = _observation_by_id(
        observations,
        "obs_issue56_prompt_mcp_body_2",
    )
    nodes = [
        _graph_node(
            node_id="node_issue56_prompt_mcp_po",
            labels=["PO470002002", "purchase order"],
            observation_id=first_body.observation_id,
            core_supertype_id="Artifact",
        ),
        _graph_node(
            node_id="node_issue56_prompt_mcp_supplier",
            labels=["SUPPLIER-ALPHA-01", "supplier"],
            observation_id=first_body.observation_id,
            core_supertype_id="Organization",
        ),
        _graph_node(
            node_id="node_issue56_prompt_mcp_origin",
            labels=["ORIGIN-TAIWAN-01", "origin"],
            observation_id=second_body.observation_id,
            core_supertype_id="Location",
        ),
    ]
    edges = [
        _graph_edge(
            edge_id="edge_issue56_prompt_mcp_supplied_by",
            source_node_id=nodes[0].node_id,
            target_node_id=nodes[1].node_id,
            relation_type="supplied_by",
            observation_id=first_body.observation_id,
        ),
        _graph_edge(
            edge_id="edge_issue56_prompt_mcp_origin_in",
            source_node_id=nodes[1].node_id,
            target_node_id=nodes[2].node_id,
            relation_type="origin_in",
            observation_id=second_body.observation_id,
        ),
    ]
    view = EffectiveGraphView(
        requester_user_id=ISSUE56_DIAGNOSTIC_USER_ID,
        user_graph_revision_id="ugraph_issue56_prompt_mcp_v1",
        canonical_graph_revision_id="cgraph_issue56_prompt_mcp_v1",
        ontology_revision_id="ontology_issue56_prompt_mcp_v1",
        assembly_policy_id="assembly_issue56_prompt_mcp_v1",
        visible_nodes=nodes,
        visible_edges=edges,
    )
    return session, view


def _synthetic_observations() -> tuple[Observation, ...]:
    archive_id = "archive_issue56_prompt_mcp"
    mailbox_id = "mailbox_issue56_prompt_mcp"
    folder_path_hash = sha256_json("issue56_prompt_mcp_folder")
    asset_id = "asset_issue56_prompt_mcp_synthetic"
    extractor_run_id = "extractor_issue56_prompt_mcp_synthetic"
    permission_scope = {
        "scope_type": "workspace",
        "visibility": "restricted",
        "scope_id": ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    }
    observations: list[Observation] = [
        Observation(
            observation_id="obs_issue56_prompt_mcp_folder",
            extractor_run_id=extractor_run_id,
            observation_type="mail_folder_occurrence",
            modality="mail",
            location={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_index": 1,
            },
            confidence=1.0,
            permission_scope=permission_scope,
            created_at=_CREATED_AT,
            asset_id=asset_id,
            text="Synthetic diagnostic",
            payload={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_label": "Synthetic diagnostic",
            },
        )
    ]
    messages = (
        ("供應商", "PO470002002 供應商 SUPPLIER-ALPHA-01"),
        ("產地", "SUPPLIER-ALPHA-01 產地 ORIGIN-TAIWAN-01"),
    )
    for index, (subject, body) in enumerate(messages, start=1):
        message_id = f"issue56-prompt-mcp-{index}@example.test"
        occurrence_id = f"mailocc_issue56_prompt_mcp_{index}"
        thread_id = "thread_issue56_prompt_mcp"
        message_fingerprint = sha256_json({"fixture": "issue56_prompt_mcp", "message_index": index})
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": folder_path_hash,
            "message_id": message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": thread_id,
        }
        observations.extend(
            (
                Observation(
                    observation_id=f"obs_issue56_prompt_mcp_message_{index}",
                    extractor_run_id=extractor_run_id,
                    observation_type="email_message",
                    modality="mail",
                    location={**base_location, "message_index": index},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at=_CREATED_AT,
                    asset_id=asset_id,
                    text=subject,
                    payload={
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        "subject": subject,
                        "normalized_subject": subject,
                        "sender": f"synthetic-{index}@example.test",
                        "sent_at": _CREATED_AT,
                        "body_hash": sha256_json(body),
                        "message_fingerprint": message_fingerprint,
                        "fingerprint_policy": "formowl_mail_fingerprint_v1",
                    },
                ),
                Observation(
                    observation_id=f"obs_issue56_prompt_mcp_body_{index}",
                    extractor_run_id=extractor_run_id,
                    observation_type="email_body_segment",
                    modality="mail",
                    location={**base_location, "body_segment_index": 1},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at=_CREATED_AT,
                    asset_id=asset_id,
                    text=body,
                    payload={
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": thread_id,
                        "body_segment_index": 1,
                        "message_fingerprint": message_fingerprint,
                    },
                ),
            )
        )
    return tuple(observations)


def _graph_node(
    *,
    node_id: str,
    labels: Sequence[str],
    observation_id: str,
    core_supertype_id: str,
) -> GraphProjectionNode:
    return GraphProjectionNode(
        node_id=node_id,
        source_type="canonical_entity",
        source_id=f"entity_{node_id}",
        labels=list(labels),
        properties={
            "label": labels[0],
            "source_observation_ids": [observation_id],
            "temporal_state": "current",
            "core_supertype_id": core_supertype_id,
            "type_confidence": 0.95,
        },
        permission_scope=_DIAGNOSTIC_WORKSPACE_SCOPE,
    )


def _graph_edge(
    *,
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    observation_id: str,
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type=relation_type,
        properties={
            "canonical_relation_id": edge_id,
            "source_observation_ids": [observation_id],
        },
        permission_scope=_DIAGNOSTIC_WORKSPACE_SCOPE,
    )


def _observation_by_id(
    observations: Sequence[Observation],
    observation_id: str,
) -> Observation:
    for observation in observations:
        if observation.observation_id == observation_id:
            return observation
    raise ContractValidationError("synthetic diagnostic observation is unavailable")


def _assert_no_legacy_identity_fields(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in {"tenant", "tenant_id"}:
                raise ContractValidationError("legacy identity field is forbidden")
            _assert_no_legacy_identity_fields(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _assert_no_legacy_identity_fields(item)


__all__ = [
    "ISSUE56_DIAGNOSTIC_ARTIFACT_ID",
    "ISSUE56_DIAGNOSTIC_CLAIM_STATUS",
    "ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT",
    "ISSUE56_DIAGNOSTIC_IDENTITY_SCOPE_MODE",
    "ISSUE56_DIAGNOSTIC_SCHEMA_VERSION",
    "ISSUE56_DIAGNOSTIC_TOOL_NAME",
    "ISSUE56_DIAGNOSTIC_USER_ID",
    "ISSUE56_DIAGNOSTIC_WORKSPACE_ID",
    "ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID",
    "ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID",
    "ISSUE56_RELATION_PROJECTION_EQUIVALENCE_DIAGNOSTIC_MODE_ID",
    "ISSUE56_RELATION_PROJECTION_EQUIVALENCE_LOADER_CONTRACT_ID",
    "ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_DIAGNOSTIC_MODE_ID",
    "ISSUE56_RELATION_PROJECTION_EQUIVALENCE_V6_LOADER_CONTRACT_ID",
    "ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_DIAGNOSTIC_MODE_ID",
    "ISSUE56_RELATION_PROJECTION_OFFLINE_EQUIVALENCE_V7_LOADER_CONTRACT_ID",
    "ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID",
    "ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID",
    "ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID",
    "ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V3_MODE_ID",
    "ISSUE56_SEALED_SOURCE_DIAGNOSTIC_PROMPT",
    "ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID",
    "ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID",
    "Issue56DiagnosticComposition",
    "Issue56DiagnosticOAuthBridge",
    "Issue56SealedSourceDiagnosticInput",
    "Issue56LineageCrosswalkPrecomputeEvidence",
    "Issue56RelationProjectionBasePrecomputeEvidence",
    "Issue56GraphContentPresealEvidence",
    "Issue56OfflineEquivalencePreflightEvidence",
    "Issue56OfflineRelationPrecomputeEvidence",
    "Issue56SourceBackedPromptSelectionEvidence",
    "Issue56DiagnosticState",
    "build_issue56_diagnostic_composition",
    "build_issue56_relation_projection_equivalence_compositions",
    "build_issue56_relation_projection_equivalence_v6_compositions",
    "build_issue56_relation_projection_offline_equivalence_v7_compositions",
    "build_issue56_sealed_source_diagnostic_input",
    "build_safe_relation_projection_equivalence_arm",
    "build_safe_relation_projection_equivalence_report",
    "build_safe_relation_projection_offline_equivalence_v7_report",
    "build_safe_diagnostic_report",
    "mcp_headers",
    "mcp_initialize_request",
    "mcp_list_tools_request",
    "mcp_query_request",
    "relation_projection_cache_containers_are_isolated",
    "relation_projection_cache_evidence",
    "precompute_issue56_offline_relation_projection_base",
    "safe_blocked_report",
]
