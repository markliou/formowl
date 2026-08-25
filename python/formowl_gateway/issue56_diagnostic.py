"""Non-claim-bearing Issue #56 prompt-to-MCP diagnostic composition.

The existing synthetic fixture remains available.  The versioned sealed-source
mode accepts only a validated loader result and still uses the same connected
MCP HTTP boundary.  Neither mode reads UAT/holdout material, configures a
production store, or expands the production connected-tool policy.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
ISSUE56_SEALED_SOURCE_DIAGNOSTIC_PROMPT = ISSUE56_DIAGNOSTIC_DEFAULT_PROMPT
ISSUE56_SEALED_SOURCE_LOADER_CONTRACT_ID = "issue56_sealed_source_diagnostic_loader_v3"
ISSUE56_REAL_PROMPT_SEALED_SOURCE_LOADER_CONTRACT_ID = (
    "issue56_real_prompt_sealed_source_diagnostic_loader_v4"
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
        required=(diagnostic_mode_id == ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID),
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
    }:
        raise ContractValidationError("sealed-source diagnostic mode binding mismatch")
    real_prompt_mode = (
        source.diagnostic_mode_id == ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
    )
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


def build_issue56_diagnostic_composition(
    *,
    actor_workspace_id: str = ISSUE56_DIAGNOSTIC_WORKSPACE_ID,
    diagnostic_mode_id: str = ISSUE56_SYNTHETIC_DIAGNOSTIC_MODE_ID,
    sealed_source: Issue56SealedSourceDiagnosticInput | None = None,
) -> Issue56DiagnosticComposition:
    """Build one diagnostic query session and real connected ASGI application."""

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
            "sealed_source_real_prompt"
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
            relation_projection_base_precompute.cache_status
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
    }
    real_prompt_mode = (
        composition.diagnostic_mode_id == ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
    )
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
    }:
        diagnostic_mode_id = ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID
    sealed_mode = diagnostic_mode_id in {
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V1_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_V2_MODE_ID,
        ISSUE56_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
        ISSUE56_REAL_PROMPT_SEALED_SOURCE_DIAGNOSTIC_MODE_ID,
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
    "Issue56SourceBackedPromptSelectionEvidence",
    "Issue56DiagnosticState",
    "build_issue56_diagnostic_composition",
    "build_issue56_sealed_source_diagnostic_input",
    "build_safe_diagnostic_report",
    "mcp_headers",
    "mcp_initialize_request",
    "mcp_list_tools_request",
    "mcp_query_request",
    "safe_blocked_report",
]
