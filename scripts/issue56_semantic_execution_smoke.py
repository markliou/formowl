#!/usr/bin/env python3
"""Run the bounded Issue #56 typed semantic execution E2E POC."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from formowl_contract import (  # noqa: E402
    ContractValidationError,
    Observation,
    assert_no_public_raw_references,
    sha256_json,
)
from formowl_core import (  # noqa: E402
    DenseEmbeddingUnavailableError,
    issue56_target_dense_embedding_profile,
)
from formowl_core.tokenization import (  # noqa: E402
    MailCandidateAdmissionTokenizerProfile,
    load_issue56_target_mail_tokenizer_profile,
)
from formowl_graph import EffectiveGraphView  # noqa: E402
from formowl_graph.index import GraphProjectionEdge, GraphProjectionNode  # noqa: E402
from formowl_mail.candidates import (  # noqa: E402
    SourceIdentifierIdentityScope,
    WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
    extract_source_bound_identifier_mentions,
)
from formowl_mail import (  # noqa: E402
    ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
    ISSUE56_TARGET_RUNTIME_METHOD_ID,
    MailEvidenceBundle,
    build_authorized_semantic_mail_session,
    build_authorized_source_backed_effective_graph_view,
    build_mail_evidence_bundle,
    render_governed_evidence_answer,
    run_authorized_semantic_mail_query,
)

WORKSPACE_ID = "workspace_issue56_semantic_poc"
REQUESTER_USER_ID = "user_issue56_semantic"
CREATED_AT = "2026-08-18T07:00:00+00:00"
PUBLIC_SCOPE = {"scope_type": "public", "visibility": "public"}
ALLOWED_RELATIONS = ("origin_in", "supplied_by")
SOURCE_GRAPH_POLICY_ID = "source_backed_mail_candidate_graph_v2"
IDENTITY_SCOPE_POLICY_ID = "issue56_semantic_poc_workspace_only_approval_v1"


@dataclass(frozen=True)
class SemanticPocInputs:
    observations_by_bundle_id: dict[str, tuple[Observation, ...]]
    bundles: tuple[MailEvidenceBundle, ...]
    current_bundle: MailEvidenceBundle
    superseded_bundle: MailEvidenceBundle
    denied_bundle: MailEvidenceBundle
    effective_graph_view: EffectiveGraphView
    current_observation_hash: str
    superseded_observation_hash: str
    ontology_only_observation_hash: str


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-blocked",
        action="store_true",
        help="Return zero while preserving an explicit missing-E5 blocker.",
    )
    args = parser.parse_args(argv)
    report = run_smoke()
    print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    if report["status"] == "passed" or args.allow_blocked:
        return 0
    return 2


def run_smoke() -> dict[str, Any]:
    declared_dense_profile = issue56_target_dense_embedding_profile()
    base = {
        "artifact_id": "formowl_issue56_semantic_execution_e2e_poc_v2",
        "schema_version": 2,
        "claim_state": "poc_only_not_methodology_or_production_completion",
        "fallback_used": False,
        "dense_retrieval": {
            "encoder_id": declared_dense_profile.encoder_id,
            "model_id": declared_dense_profile.model_id,
            "model_revision": declared_dense_profile.model_revision,
            "profile_fingerprint": declared_dense_profile.profile_fingerprint,
            "dimension": declared_dense_profile.dimension,
            "status": "pinned_real_e5_required",
        },
        "completion": {
            "issue56_complete": False,
            "methodology_complete": False,
            "production_ready": False,
        },
    }
    inputs = build_semantic_poc_inputs()
    common = {
        "observations_by_bundle_id": inputs.observations_by_bundle_id,
        "bundles": inputs.bundles,
        "requester_user_id": REQUESTER_USER_ID,
        "workspace_id": WORKSPACE_ID,
        "effective_graph_view": inputs.effective_graph_view,
    }
    try:
        session = build_authorized_semantic_mail_session(
            observations_by_bundle_id=inputs.observations_by_bundle_id,
            bundles=inputs.bundles,
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
        )
        identity_scope = _semantic_poc_identity_scope()
        source_identifier_batch = extract_source_bound_identifier_mentions(
            tuple(
                observation
                for source_scope_id in sorted(inputs.observations_by_bundle_id)
                for observation in inputs.observations_by_bundle_id[source_scope_id]
                if observation.observation_type
                in {
                    "email_message",
                    "email_header",
                    "email_body_segment",
                }
                and isinstance(observation.text, str)
                and observation.text
            ),
            identity_scope=identity_scope,
            extractor_run_id="run_issue56_semantic_source_identifier_poc",
            created_at=CREATED_AT,
        )
        source_graph = build_authorized_source_backed_effective_graph_view(
            session=session,
            observations_by_bundle_id=inputs.observations_by_bundle_id,
            source_binding_fingerprint=sha256_json(
                "issue56_target_runtime_method_real_e5_probe_v1"
            ),
            source_graph_policy_id=SOURCE_GRAPH_POLICY_ID,
            identifier_mention_batch=source_identifier_batch,
        )
        target_method_relation = run_authorized_semantic_mail_query(
            observations_by_bundle_id=inputs.observations_by_bundle_id,
            bundles=inputs.bundles,
            query_text="PO470002002 與 SUPPLIER-ALPHA-01 的關係",
            requester_user_id=REQUESTER_USER_ID,
            workspace_id=WORKSPACE_ID,
            effective_graph_view=source_graph.effective_graph_view,
            allowed_relation_types=("co_occurs_with",),
            target_core_supertype_id="Artifact",
        )
        relation = run_authorized_semantic_mail_query(
            **common,
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        relation_rerun = run_authorized_semantic_mail_query(
            **common,
            query_text="PO470002002 與 ORIGIN-TAIWAN-01 的關係",
            allowed_relation_types=ALLOWED_RELATIONS,
        )
        exact = run_authorized_semantic_mail_query(
            **common,
            query_text="列出全部採購單並計數",
            exact_inventory_kind="purchase_order",
        )
        current_vs_superseded = run_authorized_semantic_mail_query(
            **common,
            query_text="PO470002002",
            target_core_supertype_id="Artifact",
        )
        ontology_mismatch = run_authorized_semantic_mail_query(
            **common,
            query_text="PO470002002",
            target_core_supertype_id="Person",
        )
        ontology_cannot_force = run_authorized_semantic_mail_query(
            **common,
            query_text="PO999999999",
            target_core_supertype_id="Artifact",
        )
        permission_denied = run_authorized_semantic_mail_query(
            **common,
            query_text="SECRET-PO-99001",
            mail_evidence_bundle_id=inputs.denied_bundle.mail_evidence_bundle_id,
        )
        cited_answer = render_governed_evidence_answer(target_method_relation)
        exact_answer = render_governed_evidence_answer(exact)
    except DenseEmbeddingUnavailableError as exc:
        report = {
            **base,
            "status": "blocked",
            "e2e_executed": False,
            "blocker": exc.reason_code,
        }
        assert_no_public_raw_references(report, "issue56_semantic_execution_e2e_poc")
        return report
    strong_rag_active = any(
        score.lexical_score > 0.0 and score.dense_score > 0.0
        for score in target_method_relation.scores
    )
    entity_signal_active = any(score.entity_score > 0.0 for score in target_method_relation.scores)
    ontology_signal_active = any(
        score.ontology_bonus > 0.0 for score in target_method_relation.scores
    )
    graph_signal_active = target_method_relation.graph_path_count > 0 and all(
        hop.cited_observation_hashes
        for path in target_method_relation.graph_paths
        for hop in path.hops
    )
    exact_path_active = (
        exact.status == "complete_authorized_scope"
        and exact.exact_result is not None
        and exact.exact_result.coverage.authorized_scope_complete
        and exact_answer.status == "exact_complete"
    )
    cited_answer_active = (
        target_method_relation.status == "ok"
        and cited_answer.status == "answered"
        and bool(cited_answer.citation_hashes)
    )
    target_method_active = all(
        (
            target_method_relation.runtime_method_id == ISSUE56_TARGET_RUNTIME_METHOD_ID,
            target_method_relation.runtime_method_fingerprint
            == ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
            strong_rag_active,
            entity_signal_active,
            graph_signal_active,
            ontology_signal_active,
            exact_path_active,
            cited_answer_active,
        )
    )
    method_execution_fingerprint = sha256_json(
        {
            "runtime_method_id": target_method_relation.runtime_method_id,
            "runtime_method_fingerprint": (target_method_relation.runtime_method_fingerprint),
            "execution_component_fingerprint": (
                target_method_relation.execution_component_fingerprint
            ),
            "plan_fingerprint": target_method_relation.plan_fingerprint,
            "graph_revision_fingerprint": (target_method_relation.graph_revision_fingerprint),
            "answer_model_id": cited_answer.answer_model_id,
            "answer_prompt_fingerprint": cited_answer.prompt_fingerprint,
            "answer_budget_fingerprint": cited_answer.budget_fingerprint,
            "identity_scope_mode": identity_scope.identity_scope_mode,
            "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
            "identity_scope_attestation_fingerprint": (
                identity_scope.identity_scope_attestation_fingerprint
            ),
            "identity_scope_policy_fingerprint": (identity_scope.identity_scope_policy_fingerprint),
            "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
            "spec_approval_fingerprint": identity_scope.spec_approval_fingerprint,
            "legacy_path_used": False,
            "fallback_used": False,
        }
    )
    report = {
        **base,
        "status": "passed" if target_method_active else "blocked",
        "e2e_executed": True,
        "runtime_method": {
            "method_id": ISSUE56_TARGET_RUNTIME_METHOD_ID,
            "method_fingerprint": ISSUE56_TARGET_RUNTIME_METHOD_FINGERPRINT,
            "method_execution_fingerprint": method_execution_fingerprint,
            "normal_entrypoint": "run_authorized_semantic_mail_query",
            "lexical_profile_id": session.index.tokenizer_id,
            "lexical_profile_fingerprint": session.index.profile_fingerprint,
            "strong_rag_active": strong_rag_active,
            "entity_signal_active": entity_signal_active,
            "candidate_graph_signal_active": source_graph.edge_count > 0,
            "candidate_graph_policy_id": source_graph.graph_policy_id,
            "candidate_graph_only": source_graph.to_safe_dict()["candidate_graph_only"],
            "candidate_graph_relation_type_hashes": list(source_graph.relation_type_hashes),
            "identity_scope_mode": identity_scope.identity_scope_mode,
            "identity_scope_fingerprint": identity_scope.identity_scope_fingerprint,
            "identity_scope_attestation_fingerprint": (
                identity_scope.identity_scope_attestation_fingerprint
            ),
            "identity_scope_policy_fingerprint": (identity_scope.identity_scope_policy_fingerprint),
            "operator_approval_fingerprint": identity_scope.operator_approval_fingerprint,
            "spec_approval_fingerprint": identity_scope.spec_approval_fingerprint,
            "tenant_identity_present": identity_scope.tenant_id is not None,
            "soft_ontology_signal_active": ontology_signal_active,
            "graph_signal_active": graph_signal_active,
            "exact_path_active": exact_path_active,
            "cited_answer_active": cited_answer_active,
            "legacy_path_used": False,
            "fallback_used": False,
        },
        "dense_retrieval": {
            **base["dense_retrieval"],
            "status": relation.dense_encoder_status,
            "execution_component_fingerprint": (relation.execution_component_fingerprint),
        },
        "scenarios": {
            "target_method_normal_path": {
                "result": target_method_relation.to_safe_dict(),
                "answer": cited_answer.to_safe_dict(),
                "source_graph": source_graph.to_safe_dict(),
            },
            "relation_across_messages": relation.to_safe_dict(),
            "exact_inventory_count": exact.to_safe_dict(),
            "exact_inventory_answer": exact_answer.to_safe_dict(),
            "current_vs_superseded": current_vs_superseded.to_safe_dict(),
            "ontology_mismatch_retained": ontology_mismatch.to_safe_dict(),
            "ontology_cannot_force": ontology_cannot_force.to_safe_dict(),
            "permission_denied": permission_denied.to_safe_dict(),
            "unsupported_hop": {
                "status": ("rejected" if relation.rejected_hop_count > 0 else "not_observed"),
                "rejected_hop_count": relation.rejected_hop_count,
            },
            "deterministic_rerun": {
                "status": (
                    "matched"
                    if relation.result_fingerprint == relation_rerun.result_fingerprint
                    else "mismatch"
                ),
                "first_result_fingerprint": relation.result_fingerprint,
                "second_result_fingerprint": relation_rerun.result_fingerprint,
            },
        },
        "completion": {**base["completion"], "focused_e2e_poc_executed": True},
    }
    assert_no_public_raw_references(report, "issue56_semantic_execution_e2e_poc")
    return report


def _semantic_poc_identity_scope() -> SourceIdentifierIdentityScope:
    """Return one deterministic synthetic approval binding for this POC only."""

    scope_payload = {
        "mode": WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        "workspace_id": WORKSPACE_ID,
    }
    return SourceIdentifierIdentityScope(
        identity_scope_mode=WORKSPACE_ONLY_IDENTITY_SCOPE_MODE,
        identity_scope_fingerprint=sha256_json(scope_payload),
        workspace_id=WORKSPACE_ID,
        identity_scope_attestation_fingerprint=sha256_json(
            {
                "attestation_id": "issue56_semantic_poc_identity_scope_attestation_v1",
                "scope": scope_payload,
                "claim_boundary": "synthetic_poc_only_not_operator_attestation",
            }
        ),
        identity_scope_policy_fingerprint=sha256_json(IDENTITY_SCOPE_POLICY_ID),
        operator_approval_fingerprint=sha256_json(
            {
                "approval_id": "issue56_semantic_poc_fixture_approval_v1",
                "claim_boundary": "synthetic_test_fixture_only",
            }
        ),
        tenant_id=None,
        spec_approval_fingerprint=sha256_json(
            {
                "approval_kind": "spec_and_operator_approval",
                "spec_approval_id": "issue56_semantic_poc_workspace_only_v1",
            }
        ),
    )


def build_semantic_poc_inputs() -> SemanticPocInputs:
    current_observations = _mail_observations(
        namespace="current",
        messages=(
            ("目前供應商", "PO470002002 供應商 SUPPLIER-ALPHA-01"),
            ("目前產地", "SUPPLIER-ALPHA-01 產地 ORIGIN-TAIWAN-01"),
            ("另一採購單", "PO470002004 交期 2026-10-01"),
        ),
    )
    superseded_observations = _mail_observations(
        namespace="superseded",
        messages=(("已取代交期", "PO470002002 舊交期 2026-08-01"),),
    )
    denied_observations = _mail_observations(
        namespace="denied",
        messages=(("限制資料", "SECRET-PO-99001 付款條件 PRIVATE-TERM-77"),),
    )
    current_bundle = _build_bundle(
        observations=current_observations,
        namespace="current",
        owner_user_id=REQUESTER_USER_ID,
    )
    superseded_bundle = _build_bundle(
        observations=superseded_observations,
        namespace="superseded",
        owner_user_id=REQUESTER_USER_ID,
    )
    denied_bundle = _build_bundle(
        observations=denied_observations,
        namespace="denied",
        owner_user_id="user_issue56_denied_owner",
    )
    current_body_1 = _observation_by_id(
        current_observations,
        "obs_issue56_semantic_current_body_1",
    )
    current_body_2 = _observation_by_id(
        current_observations,
        "obs_issue56_semantic_current_body_2",
    )
    current_body_3 = _observation_by_id(
        current_observations,
        "obs_issue56_semantic_current_body_3",
    )
    superseded_body = _observation_by_id(
        superseded_observations,
        "obs_issue56_semantic_superseded_body_1",
    )
    visible_nodes = [
        _node(
            "node_issue56_po_current",
            labels=["PO470002002", "purchase order"],
            source_observation_ids=[current_body_1.observation_id],
            temporal_state="current",
            core_supertype_id="Artifact",
            inventory_kind="purchase_order",
            inventory_value="PO470002002",
        ),
        _node(
            "node_issue56_supplier",
            labels=["SUPPLIER-ALPHA-01", "supplier"],
            source_observation_ids=[current_body_1.observation_id],
            temporal_state="current",
            core_supertype_id="Organization",
        ),
        _node(
            "node_issue56_origin",
            labels=["ORIGIN-TAIWAN-01", "origin"],
            source_observation_ids=[current_body_2.observation_id],
            temporal_state="current",
            core_supertype_id="Location",
        ),
        _node(
            "node_issue56_po_other",
            labels=["PO470002004", "purchase order"],
            source_observation_ids=[current_body_3.observation_id],
            temporal_state="current",
            core_supertype_id="Artifact",
            inventory_kind="purchase_order",
            inventory_value="PO470002004",
        ),
        _node(
            "node_issue56_po_superseded",
            labels=["PO470002002", "purchase order"],
            source_observation_ids=[superseded_body.observation_id],
            temporal_state="superseded",
            core_supertype_id="Artifact",
            inventory_kind="purchase_order",
            inventory_value="PO470002002",
        ),
    ]
    visible_edges = [
        _edge(
            "edge_issue56_supplied_by",
            source_node_id="node_issue56_po_current",
            target_node_id="node_issue56_supplier",
            relation_type="supplied_by",
            source_observation_ids=[current_body_1.observation_id],
        ),
        _edge(
            "edge_issue56_origin_in",
            source_node_id="node_issue56_supplier",
            target_node_id="node_issue56_origin",
            relation_type="origin_in",
            source_observation_ids=[current_body_2.observation_id],
        ),
        _edge(
            "edge_issue56_unbounded",
            source_node_id="node_issue56_supplier",
            target_node_id="node_issue56_po_other",
            relation_type="unbounded_association",
            source_observation_ids=[current_body_3.observation_id],
        ),
    ]
    view = EffectiveGraphView(
        requester_user_id=REQUESTER_USER_ID,
        user_graph_revision_id="ugraph_issue56_semantic_v1",
        canonical_graph_revision_id="cgraph_issue56_semantic_v1",
        ontology_revision_id="ontology_issue56_semantic_v1",
        assembly_policy_id="assembly_issue56_semantic_v1",
        visible_nodes=visible_nodes,
        visible_edges=visible_edges,
    )
    return SemanticPocInputs(
        observations_by_bundle_id={
            current_bundle.mail_evidence_bundle_id: current_observations,
            superseded_bundle.mail_evidence_bundle_id: superseded_observations,
            denied_bundle.mail_evidence_bundle_id: denied_observations,
        },
        bundles=(current_bundle, superseded_bundle, denied_bundle),
        current_bundle=current_bundle,
        superseded_bundle=superseded_bundle,
        denied_bundle=denied_bundle,
        effective_graph_view=view,
        current_observation_hash=sha256_json(current_body_1.to_dict()),
        superseded_observation_hash=sha256_json(superseded_body.to_dict()),
        ontology_only_observation_hash=sha256_json(current_body_3.to_dict()),
    )


def load_target_profile() -> MailCandidateAdmissionTokenizerProfile:
    return load_issue56_target_mail_tokenizer_profile()


def _mail_observations(
    *,
    namespace: str,
    messages: Sequence[tuple[str, str]],
) -> tuple[Observation, ...]:
    archive_id = f"archive_issue56_semantic_{namespace}"
    mailbox_id = f"mailbox_issue56_semantic_{namespace}"
    folder_path_hash = sha256_json({"folder": namespace})
    asset_id = f"asset_issue56_semantic_{namespace}"
    extractor_run_id = f"extractor_issue56_semantic_{namespace}"
    permission_scope = {
        "scope_type": "project",
        "visibility": "restricted",
        "scope_id": f"project_issue56_semantic_{namespace}",
    }
    observations: list[Observation] = [
        Observation(
            observation_id=f"obs_issue56_semantic_{namespace}_folder",
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
            created_at=CREATED_AT,
            asset_id=asset_id,
            text="POC",
            payload={
                "archive_id": archive_id,
                "mailbox_id": mailbox_id,
                "folder_path_hash": folder_path_hash,
                "folder_label": "POC",
            },
        )
    ]
    for index, (subject, body) in enumerate(messages, start=1):
        message_id = f"issue56-semantic-{namespace}-{index}@example.test"
        occurrence_id = f"mailocc_issue56_semantic_{namespace}_{index}"
        message_fingerprint = sha256_json({"namespace": namespace, "message_index": index})
        base_location = {
            "archive_id": archive_id,
            "mailbox_id": mailbox_id,
            "folder_path_hash": folder_path_hash,
            "message_id": message_id,
            "message_occurrence_id": occurrence_id,
            "thread_id": f"thread_issue56_semantic_{namespace}",
        }
        observations.extend(
            (
                Observation(
                    observation_id=(f"obs_issue56_semantic_{namespace}_message_{index}"),
                    extractor_run_id=extractor_run_id,
                    observation_type="email_message",
                    modality="mail",
                    location={**base_location, "message_index": index},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at=CREATED_AT,
                    asset_id=asset_id,
                    text=subject,
                    payload={
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": base_location["thread_id"],
                        "subject": subject,
                        "normalized_subject": subject,
                        "sender": f"supplier-{namespace}@example.test",
                        "sent_at": CREATED_AT,
                        "body_hash": sha256_json(body),
                        "message_fingerprint": message_fingerprint,
                        "fingerprint_policy": "formowl_mail_fingerprint_v1",
                    },
                ),
                Observation(
                    observation_id=f"obs_issue56_semantic_{namespace}_body_{index}",
                    extractor_run_id=extractor_run_id,
                    observation_type="email_body_segment",
                    modality="mail",
                    location={**base_location, "body_segment_index": 1},
                    confidence=1.0,
                    permission_scope=permission_scope,
                    created_at=CREATED_AT,
                    asset_id=asset_id,
                    text=body,
                    payload={
                        "archive_id": archive_id,
                        "mailbox_id": mailbox_id,
                        "message_id": message_id,
                        "message_occurrence_id": occurrence_id,
                        "thread_id": base_location["thread_id"],
                        "body_segment_index": 1,
                        "message_fingerprint": message_fingerprint,
                    },
                ),
            )
        )
    return tuple(observations)


def _build_bundle(
    *,
    observations: Sequence[Observation],
    namespace: str,
    owner_user_id: str,
) -> MailEvidenceBundle:
    return build_mail_evidence_bundle(
        observations,
        workspace_id=WORKSPACE_ID,
        owner_user_id=owner_user_id,
        source_asset_id=f"asset_issue56_semantic_{namespace}",
        archive_sha256=sha256_json({"archive": namespace}),
        producer_type="server_side_parser",
        parser_name="existing_observation_issue56_semantic_poc",
        parser_version="issue56_semantic_poc_v1",
        upload_session_id=f"upload_issue56_semantic_{namespace}",
        created_at=CREATED_AT,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
    )


def _node(
    node_id: str,
    *,
    labels: list[str],
    source_observation_ids: list[str],
    temporal_state: str,
    core_supertype_id: str,
    inventory_kind: str | None = None,
    inventory_value: str | None = None,
) -> GraphProjectionNode:
    properties: dict[str, Any] = {
        "label": labels[0],
        "source_observation_ids": source_observation_ids,
        "temporal_state": temporal_state,
        "core_supertype_id": core_supertype_id,
        "type_confidence": 0.95,
    }
    if inventory_kind is not None:
        properties["inventory_kind"] = inventory_kind
    if inventory_value is not None:
        properties["inventory_value"] = inventory_value
    return GraphProjectionNode(
        node_id=node_id,
        source_type="canonical_entity",
        source_id=f"entity_{node_id}",
        labels=labels,
        properties=properties,
        permission_scope=PUBLIC_SCOPE,
    )


def _edge(
    edge_id: str,
    *,
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    source_observation_ids: list[str],
) -> GraphProjectionEdge:
    return GraphProjectionEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        relation_type=relation_type,
        properties={
            "canonical_relation_id": edge_id,
            "source_observation_ids": source_observation_ids,
        },
        permission_scope=PUBLIC_SCOPE,
    )


def _observation_by_id(
    observations: Sequence[Observation],
    observation_id: str,
) -> Observation:
    for observation in observations:
        if observation.observation_id == observation_id:
            return observation
    raise ContractValidationError("semantic POC Observation fixture is unavailable")


if __name__ == "__main__":
    raise SystemExit(main())
