"""Load one sealed Issue #56 mail source into the existing authorized runtime.

This module is intentionally a narrow diagnostic intake adapter.  It validates
the immutable source, materialization, identity-scope, and candidate artifacts
through their existing owner contracts, then constructs the existing
``AuthorizedSemanticMailSession`` and source-backed candidate graph.  It does
not parse a source archive, read a UAT manifest, execute a query, or write
canonical graph state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import stat
import time
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from formowl_contract import (
    ContractValidationError,
    Observation,
    PermissionScope,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_graph import EffectiveGraphView

from .bundle import MailEvidenceBundle
from .candidates import (
    SourceBoundIdentifierMentionBatch,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
)
from .hybrid import (
    AuthorizedHybridMailIndex,
    AuthorizedSemanticMailSession,
    EvidenceIdentityLineageCrosswalk,
    RelationProjectionBasePrecompute,
    SourceBackedGraphBuild,
    build_authorized_semantic_observation_session,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
    precompute_evidence_identity_lineage_crosswalk,
    precompute_relation_projection_base,
)
from .query import (
    build_authorized_observation_snippet_index,
    normalized_authorized_observation_lineages,
    source_occurrence_lineage_from_observation,
)
from .semantic_plan import validated_authorized_semantic_source

from scripts import issue56_identity_scope_attestation as identity_attestation
from scripts import issue56_simulated_uat as simulated_uat
from scripts import issue56_source_identifier_candidates as candidate_builder


ARTIFACT_ID = "formowl_issue56_sealed_source_diagnostic_load_v1"
SCHEMA_VERSION = 1
SOURCE_ARTIFACT_CATEGORY = "sealed_source_complete_retrieval_ready_mail_v1"
IDENTITY_SCOPE_MODE = WORKSPACE_ONLY_IDENTITY_SCOPE_MODE
WORKSPACE_ID = "workspace_formowl"
APPROVER_ACTOR = "user_full_pst_domain_hard_case_eval_owner"
SOURCE_GRAPH_POLICY_ID = "source_backed_mail_candidate_graph_v2"
SUPPLEMENTAL_OBSERVATION_ARTIFACT_ID = (
    "formowl_issue56_supplemental_observation_partition_v1"
)

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_SOURCE_BYTES = 1024 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
_MAX_SAFE_BYTES = 16 * 1024 * 1024


class Issue56SealedSourceLoadError(RuntimeError):
    """Fail-closed error carrying one stable, public-safe reason code."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


@dataclass(frozen=True)
class Issue56SealedSourceLoad:
    """Private runtime objects plus a hash/count/status-only public binding."""

    observations: tuple[Observation, ...] = field(repr=False)
    observations_by_bundle_id: Mapping[str, Sequence[Observation]] = field(
        repr=False,
        compare=False,
    )
    source_bundle: MailEvidenceBundle = field(repr=False, compare=False)
    query_bundle: MailEvidenceBundle = field(repr=False, compare=False)
    session: AuthorizedSemanticMailSession = field(repr=False, compare=False)
    index: AuthorizedHybridMailIndex = field(repr=False, compare=False)
    identifier_mention_batch: SourceBoundIdentifierMentionBatch = field(
        repr=False,
        compare=False,
    )
    graph_build: SourceBackedGraphBuild = field(repr=False, compare=False)
    effective_graph_view: EffectiveGraphView = field(repr=False, compare=False)
    safe_binding: Mapping[str, Any]


def load_issue56_sealed_source(
    *,
    retrieval_snapshot_path: Path,
    expected_retrieval_snapshot_sha256: str,
    bundle_artifact_path: Path,
    expected_bundle_artifact_sha256: str,
    retrieval_report_path: Path,
    expected_retrieval_report_sha256: str,
    materialized_work_dir: Path,
    expected_materialization_artifact_sha256: str,
    expected_materialization_safe_report_sha256: str,
    identity_scope_attestation_path: Path,
    expected_identity_scope_attestation_sha256: str,
    identity_scope_safe_report_path: Path,
    expected_identity_scope_safe_report_sha256: str,
    source_identifier_candidate_artifact_path: Path,
    expected_source_identifier_candidate_artifact_sha256: str,
    source_identifier_candidate_safe_report_path: Path,
    expected_source_identifier_candidate_safe_report_sha256: str,
    expected_identity_scope_fingerprint: str,
    identity_scope_mode: str,
    workspace_id: str,
    approver_actor: str,
    requester_user_id: str,
    include_participant_authorization_observations: bool = False,
    supplemental_observation_artifact_path: Path | None = None,
    expected_supplemental_observation_artifact_sha256: str | None = None,
    supplemental_parent_snapshot_path: Path | None = None,
    expected_supplemental_parent_snapshot_sha256: str | None = None,
) -> Issue56SealedSourceLoad:
    """Validate one immutable source package and build existing runtime objects.

    The caller supplies every byte seal and identity binding explicitly.  The
    function accepts only the approved workspace-only diagnostic identity and
    rejects an exact ``tenant_id`` key anywhere in the decoded package.
    """

    _validate_fixed_identity_inputs(
        identity_scope_mode=identity_scope_mode,
        workspace_id=workspace_id,
        approver_actor=approver_actor,
        requester_user_id=requester_user_id,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
    )
    supplemental_inputs = (
        supplemental_observation_artifact_path,
        expected_supplemental_observation_artifact_sha256,
        supplemental_parent_snapshot_path,
        expected_supplemental_parent_snapshot_sha256,
    )
    if any(value is not None for value in supplemental_inputs) and not all(
        value is not None for value in supplemental_inputs
    ):
        raise Issue56SealedSourceLoadError(
            "supplemental_observation_artifact_binding_incomplete"
        )

    snapshot_bytes, snapshot = _read_sealed_json(
        retrieval_snapshot_path,
        expected_sha256=expected_retrieval_snapshot_sha256,
        maximum_bytes=_MAX_SOURCE_BYTES,
        reason_prefix="retrieval_snapshot",
    )
    report_bytes, retrieval_report = _read_sealed_json(
        retrieval_report_path,
        expected_sha256=expected_retrieval_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="retrieval_report",
    )
    _reject_tenant_id(snapshot, "retrieval_snapshot")
    _reject_tenant_id(retrieval_report, "retrieval_report")
    try:
        source_observations, source_inventory = candidate_builder._validate_retrieval_inputs(
            snapshot,
            retrieval_report,
        )
        selected_observations, observation_selection_binding = (
            candidate_builder._select_source_observations(
                observations=source_observations,
                snapshot=snapshot,
                snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
                report=retrieval_report,
                report_byte_sha256=_sha256_bytes(report_bytes),
                materialized_work_dir=materialized_work_dir,
                expected_materialization_artifact_sha256=(expected_materialization_artifact_sha256),
                expected_materialization_safe_report_sha256=(
                    expected_materialization_safe_report_sha256
                ),
            )
        )
    except candidate_builder.SourceIdentifierCandidateError as exc:
        raise Issue56SealedSourceLoadError(exc.reason_code) from exc
    _reject_tenant_id(observation_selection_binding, "materialization_binding")
    for observation in selected_observations:
        _reject_tenant_id(observation.to_dict(), "materialized_observation")

    bundle_bytes, bundle_artifact = _read_sealed_json(
        bundle_artifact_path,
        expected_sha256=expected_bundle_artifact_sha256,
        maximum_bytes=_MAX_SOURCE_BYTES,
        reason_prefix="bundle_artifact",
    )
    _reject_tenant_id(bundle_artifact, "bundle_artifact")
    try:
        retrieval_intake = simulated_uat._load_native_retrieval_ready_bundle_intake(
            bundle_artifact_path=bundle_artifact_path,
            expected_bundle_artifact_sha256=expected_bundle_artifact_sha256,
            report_path=retrieval_report_path,
            expected_report_sha256=expected_retrieval_report_sha256,
        )
        source_bundle = MailEvidenceBundle.from_dict(retrieval_intake.bundle_payload)
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError("retrieval_ready_bundle_owner_contract_invalid") from exc
    _validate_source_bundle_identity(
        source_bundle,
        workspace_id=workspace_id,
        requester_user_id=requester_user_id,
        snapshot=snapshot,
        source_inventory_asset_id=source_inventory.source_asset_id,
    )

    attestation_bytes, private_attestation = _read_sealed_json(
        identity_scope_attestation_path,
        expected_sha256=expected_identity_scope_attestation_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="identity_scope_attestation",
    )
    attestation_safe_bytes, safe_attestation = _read_sealed_json(
        identity_scope_safe_report_path,
        expected_sha256=expected_identity_scope_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="identity_scope_safe_report",
    )
    _reject_tenant_id(private_attestation, "identity_scope_attestation")
    _reject_tenant_id(safe_attestation, "identity_scope_safe_report")
    try:
        loaded_attestation = identity_attestation.load_identity_scope_attestation(
            identity_scope_attestation_path,
            expected_sha256=expected_identity_scope_attestation_sha256,
        )
        identity_attestation.validate_safe_identity_scope_report(
            safe_attestation,
            private_artifact_bytes=attestation_bytes,
        )
    except identity_attestation.IdentityScopeAttestationError as exc:
        raise Issue56SealedSourceLoadError(exc.reason_code) from exc
    if loaded_attestation != private_attestation:
        raise Issue56SealedSourceLoadError("identity_scope_attestation_round_trip_mismatch")
    _validate_identity_attestation_binding(
        private_attestation,
        safe_attestation=safe_attestation,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
        workspace_id=workspace_id,
        approver_actor=approver_actor,
        snapshot=snapshot,
        source_inventory_asset_id=source_inventory.source_asset_id,
    )

    candidate_bytes, candidate_artifact = _read_sealed_json(
        source_identifier_candidate_artifact_path,
        expected_sha256=expected_source_identifier_candidate_artifact_sha256,
        maximum_bytes=_MAX_ARTIFACT_BYTES,
        reason_prefix="source_identifier_candidate_artifact",
    )
    candidate_safe_bytes, candidate_safe_report = _read_sealed_json(
        source_identifier_candidate_safe_report_path,
        expected_sha256=expected_source_identifier_candidate_safe_report_sha256,
        maximum_bytes=_MAX_SAFE_BYTES,
        reason_prefix="source_identifier_candidate_safe_report",
    )
    _reject_tenant_id(candidate_artifact, "source_identifier_candidate_artifact")
    _reject_tenant_id(
        candidate_safe_report,
        "source_identifier_candidate_safe_report",
    )
    try:
        candidate_builder.validate_private_identifier_candidate_artifact(candidate_artifact)
        candidate_builder.validate_safe_identifier_candidate_report(
            candidate_safe_report,
            private_artifact_bytes=candidate_bytes,
        )
    except candidate_builder.SourceIdentifierCandidateError as exc:
        raise Issue56SealedSourceLoadError(exc.reason_code) from exc
    _validate_candidate_attestation_binding(
        candidate_artifact,
        candidate_safe_report=candidate_safe_report,
        private_attestation=private_attestation,
        expected_attestation_sha256=expected_identity_scope_attestation_sha256,
        expected_identity_scope_fingerprint=expected_identity_scope_fingerprint,
        workspace_id=workspace_id,
    )

    selected_by_id = {
        observation.observation_id: observation for observation in selected_observations
    }
    selected_hash_by_id = {
        observation_id: sha256_json(observation.to_dict())
        for observation_id, observation in selected_by_id.items()
    }
    try:
        candidate_intake = simulated_uat._load_source_identifier_candidate_intake(
            artifact_path=source_identifier_candidate_artifact_path,
            expected_artifact_sha256=(expected_source_identifier_candidate_artifact_sha256),
            expected_identity_scope_fingerprint=(expected_identity_scope_fingerprint),
            expected_workspace_id=workspace_id,
            selected_observations_by_id=selected_by_id,
            selected_observation_hash_by_id=selected_hash_by_id,
            retrieval_ready_binding=retrieval_intake.safe_binding,
        )
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError(
            "source_identifier_candidate_owner_contract_invalid"
        ) from exc
    if candidate_intake.projected_batch.tenant_id is not None:
        raise Issue56SealedSourceLoadError("workspace_only_tenant_fabrication")

    query_bundle = _project_query_bundle(
        source_bundle,
        selected_observations=selected_observations,
    )
    supplemental_bytes: bytes | None = None
    supplemental_parent_bytes: bytes | None = None
    supplemental_observations: tuple[Observation, ...] = ()
    supplemental_binding: Mapping[str, Any] | None = None
    if supplemental_observation_artifact_path is not None:
        assert expected_supplemental_observation_artifact_sha256 is not None
        assert supplemental_parent_snapshot_path is not None
        assert expected_supplemental_parent_snapshot_sha256 is not None
        supplemental_parent_bytes, supplemental_parent = _read_sealed_json(
            supplemental_parent_snapshot_path,
            expected_sha256=expected_supplemental_parent_snapshot_sha256,
            maximum_bytes=_MAX_ARTIFACT_BYTES,
            reason_prefix="supplemental_parent_snapshot",
        )
        supplemental_bytes, supplemental_artifact = _read_sealed_json(
            supplemental_observation_artifact_path,
            expected_sha256=expected_supplemental_observation_artifact_sha256,
            maximum_bytes=_MAX_ARTIFACT_BYTES,
            reason_prefix="supplemental_observation_artifact",
        )
        _reject_tenant_id(supplemental_parent, "supplemental_parent_snapshot")
        _reject_tenant_id(supplemental_artifact, "supplemental_observation_artifact")
        supplemental_observations, supplemental_binding = (
            _validate_supplemental_observation_partition(
                supplemental_artifact,
                parent_snapshot=supplemental_parent,
                parent_snapshot_byte_sha256=_sha256_bytes(
                    supplemental_parent_bytes
                ),
                base_snapshot=snapshot,
            )
        )
    authorization_observations = tuple(selected_observations)
    if include_participant_authorization_observations:
        full_source_occurrence_ids = {
            occurrence.message_occurrence_id
            for occurrence in source_bundle.message_occurrences
        }
        participant_observations = tuple(
            observation
            for observation in source_observations
            if _observation_message_occurrence_id(observation)
            in full_source_occurrence_ids
            and (
                observation.observation_type == "email_message"
                or (
                    observation.observation_type == "email_header"
                    and str((observation.payload or {}).get("header_name", "")).casefold()
                    in {"from", "sender", "to", "cc"}
                )
            )
        )
        selected_asset_ids = {observation.asset_id for observation in selected_observations}
        selected_permission_fingerprints = {
            sha256_json(observation.permission_scope) for observation in selected_observations
        }
        if any(
            observation.asset_id not in selected_asset_ids
            or sha256_json(observation.permission_scope) not in selected_permission_fingerprints
            for observation in participant_observations
        ):
            raise Issue56SealedSourceLoadError("participant_authorization_scope_mismatch")
        if {
            occurrence_id
            for observation in participant_observations
            if (occurrence_id := _observation_message_occurrence_id(observation)) is not None
        } != full_source_occurrence_ids:
            raise Issue56SealedSourceLoadError(
                "participant_authorization_occurrence_scope_incomplete"
            )
        authorization_by_id = dict(selected_by_id)
        for observation in participant_observations:
            existing = authorization_by_id.get(observation.observation_id)
            if existing is not None and sha256_json(existing.to_dict()) != sha256_json(
                observation.to_dict()
            ):
                raise Issue56SealedSourceLoadError("participant_authorization_hash_mismatch")
            authorization_by_id[observation.observation_id] = observation
        authorization_observations = tuple(
            authorization_by_id[key] for key in sorted(authorization_by_id)
        )
    mail_authorization_observations = authorization_observations
    if supplemental_observations:
        authorization_by_id = {
            observation.observation_id: observation
            for observation in authorization_observations
        }
        for observation in supplemental_observations:
            existing = authorization_by_id.get(observation.observation_id)
            if existing is not None and existing != observation:
                raise Issue56SealedSourceLoadError(
                    "supplemental_observation_id_collision"
                )
            authorization_by_id[observation.observation_id] = observation
        authorization_observations = tuple(
            authorization_by_id[key] for key in sorted(authorization_by_id)
        )
    retrieval_observations = tuple(
        sorted(
            (
                *selected_observations,
                *(
                    observation
                    for observation in supplemental_observations
                    if observation.observation_type
                    in {"email_attachment_occurrence", "table_row"}
                ),
            ),
            key=lambda observation: observation.observation_id,
        )
    )
    observations_by_bundle_id = MappingProxyType(
        {query_bundle.mail_evidence_bundle_id: retrieval_observations}
    )
    mail_observations_by_bundle_id = MappingProxyType(
        {
            query_bundle.mail_evidence_bundle_id: tuple(
                sorted(
                    selected_observations,
                    key=lambda observation: observation.observation_id,
                )
            )
        }
    )
    authorization_observations_by_bundle_id = MappingProxyType(
        {query_bundle.mail_evidence_bundle_id: authorization_observations}
    )
    mail_authorization_by_bundle_id = MappingProxyType(
        {query_bundle.mail_evidence_bundle_id: mail_authorization_observations}
    )
    source_binding = {
        "artifact_id": ARTIFACT_ID,
        "source_artifact_category": SOURCE_ARTIFACT_CATEGORY,
        "retrieval_ready_binding_fingerprint": retrieval_intake.safe_binding[
            "input_binding_fingerprint"
        ],
        "observation_selection_binding_fingerprint": sha256_json(
            observation_selection_binding
        ),
        "candidate_binding_fingerprint": candidate_intake.safe_binding[
            "binding_fingerprint"
        ],
        "identity_scope_fingerprint": expected_identity_scope_fingerprint,
    }
    if supplemental_binding is not None:
        source_binding["supplemental_observation_partition_fingerprint"] = (
            supplemental_binding["partition_fingerprint"]
        )
    source_binding_fingerprint = sha256_json(source_binding)
    try:
        mail_session = build_authorized_semantic_mail_session(
            observations_by_bundle_id=mail_observations_by_bundle_id,
            authorization_observations_by_bundle_id=mail_authorization_by_bundle_id,
            bundles=(query_bundle,),
            requester_user_id=requester_user_id,
            workspace_id=workspace_id,
            expected_profile_fingerprint=str(snapshot["tokenizer_profile_fingerprint"]),
            mail_evidence_bundle_id=query_bundle.mail_evidence_bundle_id,
        )
        session = mail_session
        runtime_scope_id = query_bundle.mail_evidence_bundle_id
        if supplemental_observations:
            runtime_scope_id = "project_formowl"
            permission_scope = PermissionScope.project(runtime_scope_id)
            authorized_source = validated_authorized_semantic_source(
                source_kind=mail_session.authorized_source.source_kind,
                workspace_id=workspace_id,
                source_scope_ids=(runtime_scope_id,),
                authorized_permission_scopes=(permission_scope,),
            )
            mail_lineages = tuple(
                source_occurrence_lineage_from_observation(
                    observation,
                    authorized_source=authorized_source,
                )
                for observation in authorization_observations
                if observation.modality == "mail"
            )
            lineages = normalized_authorized_observation_lineages(
                authorization_observations,
                authorized_source=authorized_source,
                occurrence_lineages=mail_lineages,
            )
            retrieval_ids = {
                observation.observation_id for observation in retrieval_observations
            }
            snippet_index, _ = build_authorized_observation_snippet_index(
                retrieval_observations,
                authorized_source=authorized_source,
                occurrence_lineages=tuple(
                    item
                    for item in lineages
                    if item.source_observation_id in retrieval_ids
                ),
                authorized_observation_hash_by_id={
                    observation.observation_id: sha256_json(observation.to_dict())
                    for observation in retrieval_observations
                },
                tokenizer_profile=mail_session.index._runtime_components.tokenizer_profile,
            )
            session = build_authorized_semantic_observation_session(
                authorized_source=authorized_source,
                snippet_index=snippet_index,
                authorized_observations=authorization_observations,
                retrieval_observations=retrieval_observations,
                occurrence_lineages=lineages,
                requester_user_id=requester_user_id,
                expected_profile_fingerprint=str(
                    snapshot["tokenizer_profile_fingerprint"]
                ),
            )
        if len(session.authorized_observations) != len(
            authorization_observations
        ) or session.authorized_source_scope_ids != (runtime_scope_id,):
            raise ContractValidationError("sealed source authorization projection is incomplete")
        graph_build = build_authorized_source_backed_effective_graph_view(
            session=session,
            observations_by_bundle_id=MappingProxyType(
                {runtime_scope_id: retrieval_observations}
            ),
            source_binding_fingerprint=source_binding_fingerprint,
            identifier_mention_batch=(
                None if supplemental_observations else candidate_intake.projected_batch
            ),
            source_graph_policy_id=(
                None if supplemental_observations else SOURCE_GRAPH_POLICY_ID
            ),
        )
        precompute_started_ns = time.perf_counter_ns()
        lineage_crosswalk = precompute_evidence_identity_lineage_crosswalk(
            session=session,
            effective_graph_view=graph_build.effective_graph_view,
        )
        lineage_crosswalk_precompute_elapsed_ms = round(
            (time.perf_counter_ns() - precompute_started_ns) / 1_000_000.0,
            6,
        )
        relation_projection_base_precompute = None
        relation_projection_base_precompute_elapsed_ms = None
        if not supplemental_observations:
            relation_precompute_started_ns = time.perf_counter_ns()
            relation_projection_base_precompute = precompute_relation_projection_base(
                session=session,
                effective_graph_view=graph_build.effective_graph_view,
            )
            relation_projection_base_precompute_elapsed_ms = round(
                (time.perf_counter_ns() - relation_precompute_started_ns) / 1_000_000.0,
                6,
            )
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError("authorized_runtime_source_binding_invalid") from exc

    safe_binding = _safe_binding(
        snapshot=snapshot,
        retrieval_report=retrieval_report,
        retrieval_ready_binding=retrieval_intake.safe_binding,
        retrieval_snapshot_byte_sha256=_sha256_bytes(snapshot_bytes),
        bundle_artifact_byte_sha256=_sha256_bytes(bundle_bytes),
        materialization_artifact_byte_sha256=(expected_materialization_artifact_sha256),
        materialization_safe_report_byte_sha256=(expected_materialization_safe_report_sha256),
        attestation_artifact_byte_sha256=_sha256_bytes(attestation_bytes),
        attestation_safe_report_byte_sha256=_sha256_bytes(attestation_safe_bytes),
        candidate_artifact_byte_sha256=_sha256_bytes(candidate_bytes),
        candidate_safe_report_byte_sha256=_sha256_bytes(candidate_safe_bytes),
        identity_scope_fingerprint=expected_identity_scope_fingerprint,
        attestation=private_attestation,
        candidate_binding=candidate_intake.safe_binding,
        observation_selection_binding=observation_selection_binding,
        source_observation_count=len(source_observations),
        selected_observation_count=len(selected_observations),
        source_bundle=source_bundle,
        query_bundle=query_bundle,
        session=session,
        graph_build=graph_build,
        source_binding_fingerprint=source_binding_fingerprint,
        lineage_crosswalk=lineage_crosswalk,
        lineage_crosswalk_precompute_elapsed_ms=(lineage_crosswalk_precompute_elapsed_ms),
        relation_projection_base_precompute=(relation_projection_base_precompute),
        relation_projection_base_precompute_elapsed_ms=(
            relation_projection_base_precompute_elapsed_ms
        ),
        supplemental_artifact_byte_sha256=(
            _sha256_bytes(supplemental_bytes)
            if supplemental_bytes is not None
            else None
        ),
        supplemental_parent_snapshot_byte_sha256=(
            _sha256_bytes(supplemental_parent_bytes)
            if supplemental_parent_bytes is not None
            else None
        ),
        supplemental_binding=supplemental_binding,
    )
    return Issue56SealedSourceLoad(
        observations=retrieval_observations,
        observations_by_bundle_id=observations_by_bundle_id,
        source_bundle=source_bundle,
        query_bundle=query_bundle,
        session=session,
        index=session.index,
        identifier_mention_batch=candidate_intake.projected_batch,
        graph_build=graph_build,
        effective_graph_view=graph_build.effective_graph_view,
        safe_binding=MappingProxyType(safe_binding),
    )


def _validate_fixed_identity_inputs(
    *,
    identity_scope_mode: str,
    workspace_id: str,
    approver_actor: str,
    requester_user_id: str,
    expected_identity_scope_fingerprint: str,
) -> None:
    if identity_scope_mode != IDENTITY_SCOPE_MODE:
        raise Issue56SealedSourceLoadError("identity_scope_mode_mismatch")
    if workspace_id != WORKSPACE_ID:
        raise Issue56SealedSourceLoadError("workspace_binding_mismatch")
    if approver_actor != APPROVER_ACTOR:
        raise Issue56SealedSourceLoadError("approver_binding_mismatch")
    if requester_user_id != approver_actor:
        raise Issue56SealedSourceLoadError("requester_approver_binding_mismatch")
    _require_sha256(
        expected_identity_scope_fingerprint,
        "identity_scope_fingerprint_invalid",
    )


def _validate_source_bundle_identity(
    bundle: MailEvidenceBundle,
    *,
    workspace_id: str,
    requester_user_id: str,
    snapshot: Mapping[str, Any],
    source_inventory_asset_id: str,
) -> None:
    session = bundle.mail_import_session
    if (
        session.workspace_id != workspace_id
        or session.owner_user_id != requester_user_id
        or session.source_asset_id != source_inventory_asset_id
        or session.archive_sha256 != snapshot.get("source_asset_sha256")
    ):
        raise Issue56SealedSourceLoadError("source_bundle_identity_binding_mismatch")


def _validate_identity_attestation_binding(
    attestation: Mapping[str, Any],
    *,
    safe_attestation: Mapping[str, Any],
    expected_identity_scope_fingerprint: str,
    workspace_id: str,
    approver_actor: str,
    snapshot: Mapping[str, Any],
    source_inventory_asset_id: str,
) -> None:
    scope = attestation.get("identity_scope")
    approval = attestation.get("approval")
    asset_binding = attestation.get("asset_binding")
    if not all(isinstance(value, Mapping) for value in (scope, approval, asset_binding)):
        raise Issue56SealedSourceLoadError("identity_scope_attestation_binding_invalid")
    assert isinstance(scope, Mapping)
    assert isinstance(approval, Mapping)
    assert isinstance(asset_binding, Mapping)
    if (
        scope.get("mode") != IDENTITY_SCOPE_MODE
        or scope.get("workspace_id") != workspace_id
        or "tenant_id" in scope
        or approval.get("approver_actor") != approver_actor
        or safe_attestation.get("identity_scope_fingerprint") != expected_identity_scope_fingerprint
        or sha256_json(dict(scope)) != expected_identity_scope_fingerprint
        or asset_binding.get("asset_id") != source_inventory_asset_id
        or asset_binding.get("asset_content_hash") != snapshot.get("source_asset_sha256")
        or attestation.get("source_fingerprint") != snapshot.get("source_snapshot_fingerprint")
        or attestation.get("permission_fingerprint") != snapshot.get("permission_fingerprint")
    ):
        raise Issue56SealedSourceLoadError("identity_scope_attestation_binding_mismatch")


def _validate_candidate_attestation_binding(
    artifact: Mapping[str, Any],
    *,
    candidate_safe_report: Mapping[str, Any],
    private_attestation: Mapping[str, Any],
    expected_attestation_sha256: str,
    expected_identity_scope_fingerprint: str,
    workspace_id: str,
) -> None:
    identity_binding = artifact.get("identity_scope_binding")
    if not isinstance(identity_binding, Mapping):
        raise Issue56SealedSourceLoadError("candidate_identity_scope_binding_invalid")
    if (
        artifact.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or identity_binding.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or identity_binding.get("workspace_id") != workspace_id
        or identity_binding.get("identity_scope_fingerprint") != expected_identity_scope_fingerprint
        or identity_binding.get("identity_scope_attestation_fingerprint")
        != private_attestation.get("attestation_fingerprint")
        or artifact.get("identity_scope_attestation_byte_sha256") != expected_attestation_sha256
        or artifact.get("identity_scope_attestation_fingerprint")
        != private_attestation.get("attestation_fingerprint")
        or candidate_safe_report.get("identity_scope_fingerprint")
        != expected_identity_scope_fingerprint
        or artifact.get("candidate_only") is not True
        or artifact.get("canonical_write_allowed") is not False
        or artifact.get("overflow_count") != 0
    ):
        raise Issue56SealedSourceLoadError("candidate_identity_scope_binding_mismatch")


def _validate_supplemental_observation_partition(
    artifact: Mapping[str, Any],
    *,
    parent_snapshot: Mapping[str, Any],
    parent_snapshot_byte_sha256: str,
    base_snapshot: Mapping[str, Any],
) -> tuple[tuple[Observation, ...], Mapping[str, Any]]:
    source = parent_snapshot.get("source")
    binding = {
        "artifact_type": parent_snapshot.get("artifact_type"),
        "schema_version": parent_snapshot.get("schema_version"),
        "artifact_byte_sha256": parent_snapshot_byte_sha256,
        "artifact_commitment": parent_snapshot.get("artifact_commitment"),
        "record_stream_fingerprint": parent_snapshot.get("record_stream_fingerprint"),
        "record_count": parent_snapshot.get("record_count"),
        "source_asset_id": source.get("source_asset_id") if isinstance(source, Mapping) else None,
        "source_fingerprint": source.get("source_fingerprint") if isinstance(source, Mapping) else None,
        "permission_scope_fingerprint": source.get("permission_scope_fingerprint") if isinstance(source, Mapping) else None,
        "selection_checkpoint_fingerprint": source.get("selection_checkpoint_fingerprint") if isinstance(source, Mapping) else None,
    }
    if (
        binding["artifact_type"] != "formowl_diagnostic_current_export_table_snapshot_v2"
        or binding["schema_version"] != 2
        or not isinstance(source, Mapping)
        or not isinstance(parent_snapshot.get("records"), list)
        or binding["record_count"] != len(parent_snapshot["records"])
        or (parent_snapshot.get("capture") or {}).get("candidate_only") is not True
        or (parent_snapshot.get("capture") or {}).get("canonical_kg") is not False
        or source.get("workspace_id") != WORKSPACE_ID
        or source.get("owner_user_id") != APPROVER_ACTOR
        or binding["permission_scope_fingerprint"] != base_snapshot.get("permission_fingerprint")
        or not isinstance(binding["source_asset_id"], str)
        or not binding["source_asset_id"]
    ):
        raise Issue56SealedSourceLoadError("supplemental_parent_snapshot_contract_invalid")
    for key in ("artifact_byte_sha256", "artifact_commitment", "record_stream_fingerprint", "source_fingerprint", "permission_scope_fingerprint", "selection_checkpoint_fingerprint"):
        _require_sha256(binding[key], "supplemental_parent_snapshot_contract_invalid")
    raw = artifact.get("observations")
    counts = artifact.get("counts")
    expected_base = {key: base_snapshot.get(key) for key in ("source_snapshot_fingerprint", "source_asset_sha256", "source_inventory_fingerprint", "permission_fingerprint")}
    if (
        set(artifact) != {"artifact_id", "schema_version", "identity_scope_mode", "workspace_id", "approver_actor", "base_source_binding", "v25_parent_snapshot_binding", "counts", "observations"}
        or artifact.get("artifact_id") != SUPPLEMENTAL_OBSERVATION_ARTIFACT_ID
        or artifact.get("schema_version") != 1
        or artifact.get("identity_scope_mode") != IDENTITY_SCOPE_MODE
        or artifact.get("workspace_id") != WORKSPACE_ID
        or artifact.get("approver_actor") != APPROVER_ACTOR
        or artifact.get("base_source_binding") != expected_base
        or artifact.get("v25_parent_snapshot_binding") != binding
        or not isinstance(counts, Mapping)
        or not isinstance(raw, list)
        or not raw
    ):
        raise Issue56SealedSourceLoadError("supplemental_observation_artifact_contract_invalid")
    try:
        observations = tuple(Observation.from_dict(dict(item)) for item in raw if isinstance(item, Mapping))
    except (ContractValidationError, TypeError, ValueError) as exc:
        raise Issue56SealedSourceLoadError("supplemental_observation_contract_invalid") from exc
    if len(observations) != len(raw) or len({item.observation_id for item in observations}) != len(observations):
        raise Issue56SealedSourceLoadError("supplemental_observation_contract_invalid")
    permission = PermissionScope.project("project_formowl").to_dict()
    parents = {str((item.payload or {}).get("child_asset_id")): item for item in observations if item.observation_type == "email_attachment_occurrence"}
    if len(parents) != sum(item.observation_type == "email_attachment_occurrence" for item in observations) or any(
        item.permission_scope != permission
        or item.modality != "mail"
        or item.asset_id != binding["source_asset_id"]
        or _observation_message_occurrence_id(item) != (item.payload or {}).get("message_occurrence_id")
        or _SHA256_RE.fullmatch(str((item.payload or {}).get("raw_message_fingerprint"))) is None
        or _SHA256_RE.fullmatch(str((item.payload or {}).get("attachment_content_fingerprint"))) is None
        for item in parents.values()
    ):
        raise Issue56SealedSourceLoadError("supplemental_attachment_parent_lineage_invalid")
    children = tuple(item for item in observations if item.observation_type != "email_attachment_occurrence")
    referenced_structural_ids = {
        str((item.payload or {}).get("lineage", {}).get("source_structural_observation_id"))
        for item in children
    }
    parent_records = {}
    try:
        for record in parent_snapshot["records"]:
            structural = record["structural_observation"]
            structural_id = structural["structural_observation_id"]
            if structural_id not in referenced_structural_ids:
                continue
            rows_by_ordinal = {}
            for source_row in structural["rows"]:
                cells = source_row["cells"]
                cells_by_ordinal = {
                    source_cell["column_ordinal"]: source_cell
                    for source_cell in cells
                }
                row_ordinal = source_row["row_ordinal"]
                if (
                    len(cells_by_ordinal) != len(cells)
                    or any(
                        not isinstance(index, int) or isinstance(index, bool)
                        for index in cells_by_ordinal
                    )
                    or not isinstance(row_ordinal, int)
                    or isinstance(row_ordinal, bool)
                    or row_ordinal in rows_by_ordinal
                ):
                    raise ValueError
                rows_by_ordinal[row_ordinal] = (
                    "\t".join(
                        cells_by_ordinal[index].get("value", "")
                        for index in sorted(cells_by_ordinal)
                    ),
                    cells_by_ordinal,
                )
            if structural_id in parent_records:
                raise ValueError
            parent_records[structural_id] = (
                record,
                sha256_json(record),
                rows_by_ordinal,
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise Issue56SealedSourceLoadError(
            "supplemental_parent_record_binding_invalid"
        ) from exc
    if set(parent_records) != referenced_structural_ids:
        raise Issue56SealedSourceLoadError("supplemental_parent_record_binding_invalid")
    statuses: list[str] = []
    structural_ids: set[str] = set()
    for item in children:
        payload = item.payload or {}
        lineage = payload.get("lineage")
        structure = payload.get("table_structure")
        parent = parents.get(item.asset_id or "")
        status = structure.get("structure_status") if isinstance(structure, Mapping) else None
        structural_id = (
            lineage.get("source_structural_observation_id")
            if isinstance(lineage, Mapping)
            else None
        )
        parent_record = parent_records.get(str(structural_id))
        source_row = (
            parent_record[2].get(lineage.get("source_row_ordinal"))
            if parent_record is not None and isinstance(lineage, Mapping)
            else None
        )
        source_cell = None
        expected_value = source_row[0] if source_row is not None else None
        if item.observation_type == "table_cell" and source_row is not None:
            source_cell = source_row[1].get(lineage.get("source_column_ordinal"))
            expected_value = (
                source_cell.get("value", "") if source_cell is not None else None
            )
        if (
            item.permission_scope != permission
            or item.modality != "document"
            or item.observation_type not in {"table_row", "table_cell"}
            or parent is None
            or not isinstance(lineage, Mapping)
            or lineage.get("parent_attachment_observation_id") != parent.observation_id
            or lineage.get("source_structural_observation_id") in {None, ""}
            or status not in {"source_provided", "candidate_only"}
            or payload.get("canonical_fact_status") != "not_asserted"
            or parent_record is None
            or lineage.get("snapshot_record_fingerprint") != parent_record[1]
            or (status == "source_provided" and parent_record[0].get("record_type") != "xlsx_sheet")
            or parent_record[0]["structural_observation"].get("source_asset_id") != parent.asset_id
            or parent_record[0].get("raw_message_fingerprint") != (parent.payload or {}).get("raw_message_fingerprint")
            or parent_record[0].get("attachment_content_fingerprint") != (parent.payload or {}).get("attachment_content_fingerprint")
            or source_row is None
            or payload.get("value") != expected_value
            or item.text != expected_value
            or (
                item.observation_type == "table_cell"
                and (
                    source_cell is None
                    or payload.get("cell_state") != source_cell.get("cell_state")
                )
            )
        ):
            raise Issue56SealedSourceLoadError("supplemental_attachment_child_lineage_invalid")
        structural_ids.add(str(lineage["source_structural_observation_id"]))
        statuses.append(str(status))
    rows = sum(item.observation_type == "table_row" for item in children)
    computed = {
        "reviewed_xlsx_binding_count": len(structural_ids),
        "parent_message_occurrence_count": len({_observation_message_occurrence_id(item) for item in parents.values()}),
        "attachment_parent_count": len(parents),
        "table_row_count": rows,
        "table_cell_count": len(children) - rows,
        "source_provided_table_observation_count": statuses.count("source_provided"),
        "candidate_only_table_observation_count": statuses.count("candidate_only"),
        "authorized_supplemental_observation_count": len(observations),
        "retrieval_supplemental_observation_count": len(parents) + rows,
    }
    if not parents or not rows or not computed["table_cell_count"] or dict(counts) != computed:
        raise Issue56SealedSourceLoadError("supplemental_observation_count_mismatch")
    return observations, MappingProxyType({
        "status": "loaded",
        "partition_fingerprint": sha256_json(artifact),
        "parent_snapshot_artifact_commitment": binding["artifact_commitment"],
        "parent_snapshot_record_stream_fingerprint": binding["record_stream_fingerprint"],
        "counts": computed,
    })

def _project_query_bundle(
    source_bundle: MailEvidenceBundle,
    *,
    selected_observations: Sequence[Observation],
) -> MailEvidenceBundle:
    selected_ids = {observation.observation_id for observation in selected_observations}
    if len(selected_ids) != len(selected_observations):
        raise Issue56SealedSourceLoadError("selected_observation_id_duplicate")
    if any(
        observation.modality != "mail"
        or observation.observation_type != "email_body_segment"
        or not isinstance(observation.text, str)
        or not observation.text
        for observation in selected_observations
    ):
        raise Issue56SealedSourceLoadError("materialized_query_observation_type_unsupported")

    body_by_observation_id = {
        segment.source_observation_id: segment for segment in source_bundle.body_segments
    }
    selected_segments = [
        body_by_observation_id[observation_id]
        for observation_id in sorted(selected_ids)
        if observation_id in body_by_observation_id
    ]
    if len(selected_segments) != len(selected_ids):
        raise Issue56SealedSourceLoadError("bundle_body_observation_lineage_incomplete")
    observation_by_id = {
        observation.observation_id: observation for observation in selected_observations
    }
    if any(
        segment.text != observation_by_id[segment.source_observation_id].text
        or segment.message_occurrence_id
        != _observation_message_occurrence_id(observation_by_id[segment.source_observation_id])
        for segment in selected_segments
    ):
        raise Issue56SealedSourceLoadError("bundle_body_observation_lineage_mismatch")

    selected_message_ids = {segment.email_message_id for segment in selected_segments}
    selected_messages = [
        message
        for message in source_bundle.messages
        if message.email_message_id in selected_message_ids
    ]
    if {message.email_message_id for message in selected_messages} != selected_message_ids:
        raise Issue56SealedSourceLoadError("bundle_message_lineage_incomplete")
    selected_occurrence_ids = {segment.message_occurrence_id for segment in selected_segments}
    selected_message_occurrences = [
        occurrence
        for occurrence in source_bundle.message_occurrences
        if occurrence.message_occurrence_id in selected_occurrence_ids
    ]
    if {
        occurrence.message_occurrence_id for occurrence in selected_message_occurrences
    } != selected_occurrence_ids:
        raise Issue56SealedSourceLoadError("bundle_message_occurrence_lineage_incomplete")

    query_bundle = MailEvidenceBundle(
        mail_evidence_bundle_id=source_bundle.mail_evidence_bundle_id,
        producer_type=source_bundle.producer_type,
        mail_import_session=source_bundle.mail_import_session,
        archive_occurrences=[],
        folder_occurrences=[],
        messages=sorted(
            selected_messages,
            key=lambda message: message.email_message_id,
        ),
        message_occurrences=sorted(
            selected_message_occurrences,
            key=lambda occurrence: occurrence.email_message_occurrence_id,
        ),
        body_segments=sorted(
            selected_segments,
            key=lambda segment: segment.email_body_segment_id,
        ),
        attachments=[],
        attachment_occurrences=[],
        quoted_message_candidates=[],
        embedded_message_relations=[],
        mail_parse_run=source_bundle.mail_parse_run,
        parse_warnings=[],
        created_at=source_bundle.created_at,
    )
    MailEvidenceBundle.from_dict(query_bundle.to_dict())
    return query_bundle


def _safe_binding(
    *,
    snapshot: Mapping[str, Any],
    retrieval_report: Mapping[str, Any],
    retrieval_ready_binding: Mapping[str, Any],
    retrieval_snapshot_byte_sha256: str,
    bundle_artifact_byte_sha256: str,
    materialization_artifact_byte_sha256: str,
    materialization_safe_report_byte_sha256: str,
    attestation_artifact_byte_sha256: str,
    attestation_safe_report_byte_sha256: str,
    candidate_artifact_byte_sha256: str,
    candidate_safe_report_byte_sha256: str,
    identity_scope_fingerprint: str,
    attestation: Mapping[str, Any],
    candidate_binding: Mapping[str, Any],
    observation_selection_binding: Mapping[str, Any],
    source_observation_count: int,
    selected_observation_count: int,
    source_bundle: MailEvidenceBundle,
    query_bundle: MailEvidenceBundle,
    session: AuthorizedSemanticMailSession,
    graph_build: SourceBackedGraphBuild,
    source_binding_fingerprint: str,
    lineage_crosswalk: EvidenceIdentityLineageCrosswalk,
    lineage_crosswalk_precompute_elapsed_ms: float,
    relation_projection_base_precompute: RelationProjectionBasePrecompute | None,
    relation_projection_base_precompute_elapsed_ms: float | None,
    supplemental_artifact_byte_sha256: str | None,
    supplemental_parent_snapshot_byte_sha256: str | None,
    supplemental_binding: Mapping[str, Any] | None,
) -> dict[str, Any]:
    counts = {
        "source_observation_count": source_observation_count,
        "selected_observation_count": selected_observation_count,
        "authorized_observation_count": len(session.authorized_observations),
        "full_bundle_message_count": len(source_bundle.messages),
        "full_bundle_message_occurrence_count": len(source_bundle.message_occurrences),
        "full_bundle_body_segment_count": len(source_bundle.body_segments),
        "full_bundle_attachment_count": len(source_bundle.attachments),
        "full_bundle_attachment_occurrence_count": len(source_bundle.attachment_occurrences),
        "query_bundle_message_count": len(query_bundle.messages),
        "query_bundle_message_occurrence_count": len(query_bundle.message_occurrences),
        "query_bundle_body_segment_count": len(query_bundle.body_segments),
        "identifier_occurrence_count": int(candidate_binding["selected_mention_count"]),
        "resolved_candidate_count": int(candidate_binding["selected_resolved_candidate_count"]),
        "overflow_count": int(candidate_binding["overflow_count"]),
        "graph_source_observation_count": graph_build.source_observation_count,
        "graph_observation_node_count": graph_build.observation_node_count,
        "graph_entity_node_count": graph_build.entity_node_count,
        "graph_edge_count": graph_build.edge_count,
    }
    binding: dict[str, Any] = {
        "artifact_id": ARTIFACT_ID,
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "claim_boundary_status": "diagnostic_source_load_only_no_quality_claim",
        "methodology_readiness_status": "blocked",
        "source_artifact_category": SOURCE_ARTIFACT_CATEGORY,
        "identity_scope_mode_status": IDENTITY_SCOPE_MODE,
        "tenant_dimension_status": "not_modeled_not_fabricated",
        "candidate_only": True,
        "canonical_write_allowed": False,
        "source_graph_policy_id": graph_build.graph_policy_id,
        "retrieval_snapshot_byte_sha256": retrieval_snapshot_byte_sha256,
        "bundle_artifact_byte_sha256": bundle_artifact_byte_sha256,
        "retrieval_report_byte_sha256": retrieval_ready_binding["retrieval_report_byte_hash"],
        "materialization_artifact_byte_sha256": (materialization_artifact_byte_sha256),
        "materialization_safe_report_byte_sha256": (materialization_safe_report_byte_sha256),
        "identity_scope_attestation_byte_sha256": (attestation_artifact_byte_sha256),
        "identity_scope_safe_report_byte_sha256": (attestation_safe_report_byte_sha256),
        "source_identifier_candidate_artifact_byte_sha256": (candidate_artifact_byte_sha256),
        "source_identifier_candidate_safe_report_byte_sha256": (candidate_safe_report_byte_sha256),
        "source_snapshot_fingerprint": snapshot["source_snapshot_fingerprint"],
        "source_asset_fingerprint": snapshot["source_asset_sha256"],
        "source_inventory_fingerprint": snapshot["source_inventory_fingerprint"],
        "source_provenance_fingerprint": snapshot["source_provenance_fingerprint"],
        "permission_fingerprint": snapshot["permission_fingerprint"],
        "retrieval_snapshot_fingerprint": snapshot["snapshot_fingerprint"],
        "retrieval_report_fingerprint": retrieval_report["report_fingerprint"],
        "mail_evidence_bundle_fingerprint": retrieval_ready_binding[
            "mail_evidence_bundle_fingerprint"
        ],
        "candidate_admission_profile_fingerprint": snapshot["tokenizer_profile_fingerprint"],
        "identity_scope_fingerprint": identity_scope_fingerprint,
        "identity_scope_attestation_fingerprint": attestation["attestation_fingerprint"],
        "identity_scope_policy_fingerprint": attestation["policy_fingerprint"],
        "operator_approval_fingerprint": candidate_binding["operator_approval_fingerprint"],
        "spec_approval_fingerprint": candidate_binding["spec_approval_fingerprint"],
        "observation_selection_binding_fingerprint": sha256_json(observation_selection_binding),
        "source_identifier_mention_batch_fingerprint": (
            candidate_binding["selected_mention_batch_fingerprint"]
        ),
        "source_identifier_resolution_fingerprint": (
            candidate_binding["selected_resolution_fingerprint"]
        ),
        "source_binding_fingerprint": source_binding_fingerprint,
        "index_fingerprint": session.index.index_fingerprint,
        "graph_revision_fingerprint": graph_build.graph_revision_fingerprint,
        "graph_build_fingerprint": graph_build.build_fingerprint,
        "lineage_crosswalk_precompute": _lineage_crosswalk_precompute_safe_binding(
            lineage_crosswalk=lineage_crosswalk,
            elapsed_ms=lineage_crosswalk_precompute_elapsed_ms,
        ),
        "relation_projection_base_precompute": (
            _relation_projection_base_precompute_safe_binding(
                precompute=relation_projection_base_precompute,
                elapsed_ms=relation_projection_base_precompute_elapsed_ms,
            )
            if relation_projection_base_precompute is not None
            else {
                "status": "skipped",
                "reason": "supplemental_observation_partition_not_applicable",
                "helper_invocation_count": 0,
            }
        ),
        "counts": counts,
    }
    if supplemental_binding is not None:
        if (
            supplemental_artifact_byte_sha256 is None
            or supplemental_parent_snapshot_byte_sha256 is None
        ):
            raise Issue56SealedSourceLoadError(
                "supplemental_observation_safe_binding_invalid"
            )
        binding.update(
            supplemental_observation_artifact_byte_sha256=(
                supplemental_artifact_byte_sha256
            ),
            supplemental_parent_snapshot_byte_sha256=(
                supplemental_parent_snapshot_byte_sha256
            ),
            supplemental_parent_snapshot_artifact_commitment=(
                supplemental_binding["parent_snapshot_artifact_commitment"]
            ),
            supplemental_parent_snapshot_record_stream_fingerprint=(
                supplemental_binding["parent_snapshot_record_stream_fingerprint"]
            ),
            supplemental_observation_partition_fingerprint=(
                supplemental_binding["partition_fingerprint"]
            ),
            supplemental_observation_partition_status=supplemental_binding["status"],
        )
        counts.update(supplemental_binding["counts"])
    for field_name, value in binding.items():
        if field_name.endswith("_fingerprint") or field_name.endswith("_sha256"):
            _require_sha256(value, f"{field_name}_invalid")
    if (
        counts["authorized_observation_count"] < counts["selected_observation_count"]
        or counts["selected_observation_count"] != counts["query_bundle_body_segment_count"]
        or counts["overflow_count"] != 0
    ):
        raise Issue56SealedSourceLoadError("safe_binding_count_mismatch")
    precompute_binding = binding["lineage_crosswalk_precompute"]
    if (
        precompute_binding["index_fingerprint"] != binding["index_fingerprint"]
        or precompute_binding["graph_revision_fingerprint"] != binding["graph_revision_fingerprint"]
        or precompute_binding["source_session_binding_fingerprint"]
        != session.source_session_binding_fingerprint
        or precompute_binding["counts"]["authorized_evidence_count"]
        != counts["authorized_observation_count"]
    ):
        raise Issue56SealedSourceLoadError("lineage_crosswalk_precompute_binding_mismatch")
    relation_precompute_binding = binding["relation_projection_base_precompute"]
    if relation_projection_base_precompute is not None and (
        relation_precompute_binding["index_fingerprint"] != binding["index_fingerprint"]
        or relation_precompute_binding["graph_revision_fingerprint"]
        != binding["graph_revision_fingerprint"]
        or relation_precompute_binding["candidate_admission_profile_fingerprint"]
        != binding["candidate_admission_profile_fingerprint"]
        or relation_precompute_binding["counts"]["authorized_observation_count"]
        != counts["authorized_observation_count"]
        or relation_precompute_binding["counts"]["candidate_count"] != len(session.index.candidates)
        or relation_precompute_binding["counts"]["projected_node_count"]
        != graph_build.observation_node_count + graph_build.entity_node_count
    ):
        raise Issue56SealedSourceLoadError("relation_projection_base_precompute_binding_mismatch")
    binding["binding_fingerprint"] = sha256_json(binding)
    try:
        assert_no_public_raw_references(binding, "issue56_sealed_source_load")
    except ContractValidationError as exc:
        raise Issue56SealedSourceLoadError("safe_binding_private_reference_exposed") from exc
    _reject_tenant_id(binding, "safe_binding")
    return binding


def _lineage_crosswalk_precompute_safe_binding(
    *,
    lineage_crosswalk: EvidenceIdentityLineageCrosswalk,
    elapsed_ms: float,
) -> dict[str, Any]:
    if not isinstance(elapsed_ms, float) or elapsed_ms < 0:
        raise Issue56SealedSourceLoadError("lineage_crosswalk_precompute_elapsed_invalid")
    counts = {
        "authorized_evidence_count": lineage_crosswalk.authorized_evidence_count,
        "indexed_evidence_count": lineage_crosswalk.indexed_evidence_count,
        "occurrence_bound_evidence_count": (lineage_crosswalk.occurrence_bound_evidence_count),
        "graph_node_bound_evidence_count": (lineage_crosswalk.graph_node_bound_evidence_count),
        "graph_edge_bound_evidence_count": (lineage_crosswalk.graph_edge_bound_evidence_count),
    }
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise Issue56SealedSourceLoadError("lineage_crosswalk_precompute_count_invalid")
    cache_key_fingerprint = sha256_json(
        {
            "artifact_id": "formowl_issue56_evidence_identity_lineage_cache_key_v1",
            "index_fingerprint": lineage_crosswalk.index_fingerprint,
            "graph_revision_fingerprint": (lineage_crosswalk.graph_revision_fingerprint),
            "source_session_binding_fingerprint": (
                lineage_crosswalk.source_session_binding_fingerprint
            ),
        }
    )
    binding = {
        "artifact_id": "formowl_issue56_lineage_crosswalk_precompute_safe_v1",
        "schema_version": 1,
        "status": "passed",
        "cache_status": "primed",
        "helper_invocation_count": 1,
        "elapsed_ms": elapsed_ms,
        "crosswalk_fingerprint": lineage_crosswalk.crosswalk_fingerprint,
        "index_fingerprint": lineage_crosswalk.index_fingerprint,
        "graph_revision_fingerprint": (lineage_crosswalk.graph_revision_fingerprint),
        "source_session_binding_fingerprint": (
            lineage_crosswalk.source_session_binding_fingerprint
        ),
        "cache_key_fingerprint": cache_key_fingerprint,
        "counts": counts,
    }
    for field_name in (
        "crosswalk_fingerprint",
        "index_fingerprint",
        "graph_revision_fingerprint",
        "source_session_binding_fingerprint",
        "cache_key_fingerprint",
    ):
        _require_sha256(
            binding[field_name],
            f"lineage_crosswalk_precompute_{field_name}_invalid",
        )
    return binding


def _relation_projection_base_precompute_safe_binding(
    *,
    precompute: RelationProjectionBasePrecompute,
    elapsed_ms: float,
) -> dict[str, Any]:
    if not isinstance(elapsed_ms, float) or elapsed_ms < 0:
        raise Issue56SealedSourceLoadError("relation_projection_base_precompute_elapsed_invalid")
    binding = precompute.to_safe_dict()
    binding["helper_invocation_count"] = 1
    binding["elapsed_ms"] = elapsed_ms
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
            binding[field_name],
            f"relation_projection_base_precompute_{field_name}_invalid",
        )
    counts = binding["counts"]
    if not isinstance(counts, dict) or any(
        type(value) is not int or value < 0 for value in counts.values()
    ):
        raise Issue56SealedSourceLoadError("relation_projection_base_precompute_count_invalid")
    return binding


def _observation_message_occurrence_id(observation: Observation) -> str | None:
    for source in (observation.location, observation.payload or {}):
        value = source.get("message_occurrence_id")
        if isinstance(value, str) and value:
            return value
    return None


def _read_sealed_json(
    path: Path,
    *,
    expected_sha256: str,
    maximum_bytes: int,
    reason_prefix: str,
) -> tuple[bytes, dict[str, Any]]:
    _require_sha256(expected_sha256, f"{reason_prefix}_expected_sha256_invalid")
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise OSError("not a regular file")
        if file_stat.st_size > maximum_bytes:
            raise OSError("file exceeds maximum size")
        raw = path.read_bytes()
    except OSError as exc:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_unavailable") from exc
    if _sha256_bytes(raw) != expected_sha256:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_byte_seal_mismatch")
    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_json_invalid") from exc
    if type(payload) is not dict:
        raise Issue56SealedSourceLoadError(f"{reason_prefix}_json_invalid")
    return raw, payload


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON key")
        payload[key] = value
    return payload


def _reject_tenant_id(value: Any, reason_prefix: str) -> None:
    if isinstance(value, Mapping):
        if "tenant_id" in value:
            raise Issue56SealedSourceLoadError(f"{reason_prefix}_tenant_id_forbidden")
        for item in value.values():
            _reject_tenant_id(item, reason_prefix)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_tenant_id(item, reason_prefix)


def _require_sha256(value: Any, reason_code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise Issue56SealedSourceLoadError(reason_code)
    return value


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
