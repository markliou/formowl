"""Governed source templates and packet assembly for issue #20 evidence.

The inputs handled here are bounded summaries. They intentionally contain no
OAuth values, raw MCP/ChatGPT transcripts, email addresses, endpoint URLs,
payloads, SQL, or backend paths. The final packet is always revalidated by the
current ``oauth_mcp_harness`` authority before it is emitted.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
for import_root in (ROOT / "python", ROOT / "tests", ROOT / "scripts"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import connected_runtime_postgres_live_e2e as _live_postgresql  # noqa: E402
import oauth_mcp_harness as _authority  # noqa: E402


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_LABEL_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
_URL_RE = re.compile(r"\bhttps?://", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_BEARER_RE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE)
_RAW_PATH_RE = re.compile(
    r"(^|[\s'\"([{=,:;])(/(?:home|tmp|srv|mnt|var|root|workspace)/|[A-Za-z]:[\\/])"
)
_SQL_RE = re.compile(
    r"\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table)\b",
    re.IGNORECASE,
)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----", re.IGNORECASE)
_SENSITIVE_KEY_PARTS = {
    "access_token",
    "authorization_code",
    "client_secret",
    "code_verifier",
    "credential",
    "email",
    "id_token",
    "nonce",
    "password",
    "payload",
    "refresh_token",
    "subject",
    "token",
    "transcript",
}

_TEMPLATE_HASH = "sha256:" + ("0" * 64)
_ABSENT_VALUE_COMMITMENT = _authority.sha256_json(
    {"binding_type": "issue20_absent_value_commitment_v1"}
)

_SOURCE_SCHEMA_VERSION = 1
_MCP_SOURCE_TYPE = "issue20_mcp_inspector_governed_source"
_CHATGPT_SOURCE_TYPE = "issue20_live_chatgpt_google_governed_source"
_REVIEWER_SOURCE_TYPE = "issue20_reviewer_gate_governed_source"
_COMPLETION_SOURCE_TYPE = "issue20_completion_audit_governed_source"

_EVENT_FIELDS = {
    "sequence_index",
    "event_name",
    "status",
    "observation_commitment_hash",
    "semantic_result_count",
    "partial_state_write_count",
}
_IDENTITY_FIELDS = {
    "external_subject_commitment_hash",
    "formowl_user_binding_hash",
    "external_identity_binding_hash",
    "workspace_binding_hash",
    "role",
    "initial_session_binding_hash",
}
_RELINK_FIELDS = {
    "sequence_index",
    "relink_kind",
    "external_subject_commitment_hash",
    "formowl_user_binding_hash",
    "prior_session_binding_hash",
    "new_session_binding_hash",
}
_REVIEWER_FIELDS = {
    "sequence_index",
    "reviewer_id_hash",
    "review_area",
    "decision",
    "output_commitment_hash",
    "blocking_finding_count",
}
_COMPLETION_JOURNEY_FIELDS = {
    "sequence_index",
    "journey_name",
    "status",
    "evidence_commitment_hash",
}

_MCP_SOURCE_FIELDS = {
    "artifact_type",
    "schema_version",
    "status",
    "operator_attested",
    "endpoint_scheme",
    "inspector_version_hash",
    "negotiated_protocol_version_hash",
    "events",
    "attestations",
}
_CHATGPT_SOURCE_FIELDS = {
    "artifact_type",
    "schema_version",
    "status",
    "operator_attested",
    "endpoint_scheme",
    "callback_bootstrap_mode",
    "negotiated_protocol_version_hash",
    "identities",
    "relink_bindings",
    "events",
    "audit_records",
    "attestations",
}
_REVIEWER_SOURCE_FIELDS = {
    "artifact_type",
    "schema_version",
    "status",
    "operator_attested",
    "closure_transition_plan_hash",
    "reviewer_gate_governance_hash",
    "review_packet_commitment_hash",
    "reviewers",
    "attestations",
}
_COMPLETION_SOURCE_FIELDS = {
    "artifact_type",
    "schema_version",
    "status",
    "auditor_attested",
    "operator_attested",
    "independent_auditor_id_hash",
    "audit_output_commitment_hash",
    "implementation_contract_hash",
    "local_harness_report_hash",
    "actor_context_contract_hash",
    "documentation_contract_hash",
    "closure_transition_plan_hash",
    "reviewer_gate_governance_hash",
    "operator_execution_authority_pin_hash",
    "reviewed_layer_artifact_set_hash",
    "journeys",
    "blocking_finding_count",
    "attestations",
}

_MCP_SOURCE_ATTESTATIONS = {
    "remote_https_endpoint_observed",
    "real_mcp_inspector_used",
    "no_simulated_inspector",
    "official_inspector_latest_command_used",
    "list_tools_and_call_tool_used",
    "public_discovery_without_oauth_observed",
    "per_tool_security_schemes_observed",
    "security_schemes_meta_mirror_observed",
    "protected_tool_challenge_observed",
    "challenge_www_authenticate_error_observed",
    "challenge_error_description_observed",
    "invalid_bearer_challenge_observed",
    "inspector_oauth_login_not_attempted",
    "inspector_authenticated_journey_not_claimed",
    "no_raw_bearer_supplied",
    "no_semantic_result_or_partial_state",
    "no_sensitive_material_in_source",
}
_CHATGPT_SOURCE_ATTESTATIONS = {
    "real_chatgpt_connector_used",
    "live_google_login_observed",
    "public_https_endpoint_observed",
    "no_fake_google_provider",
    "no_simulated_chatgpt_client",
    "developer_mode_app_created_from_public_mcp",
    "tool_list_visible_after_creation",
    "new_conversation_app_enabled",
    "metadata_refresh_observed",
    "callback_bootstrap_discovery_not_counted_as_completion",
    "callback_bootstrap_no_reachable_third_party_redirect",
    "callback_bootstrap_created_no_invitation_or_active_identity_state",
    "callback_bootstrap_left_no_oauth_transaction_or_code_state",
    "final_callback_refresh_before_oauth_evidence",
    "exact_production_callback_allowlisted",
    "no_legacy_callback_for_new_app",
    "predefined_client_pkce_s256_used",
    "cimd_dcr_not_enabled_in_closed_beta",
    "public_discovery_without_oauth_observed",
    "per_tool_security_schemes_observed",
    "security_schemes_meta_mirror_observed",
    "protected_tool_challenge_observed",
    "challenge_www_authenticate_error_observed",
    "challenge_error_description_observed",
    "direct_whoami_observed",
    "direct_open_upload_session_observed",
    "model_tool_selection_safe_summary_observed",
    "model_arguments_safe_commitment_observed",
    "confirmation_result_safe_commitment_observed",
    "forgery_request_reached_gateway",
    "forgery_server_denial_audit_observed",
    "client_side_schema_rejection_not_counted_as_gateway_denial",
    "cross_workspace_schema_valid_request_reached_gateway",
    "owner_only_denial_operator_service_member_attribution_probe",
    "second_real_google_user_observed",
    "second_user_distinct_from_owner_observed",
    "second_user_member_role_and_workspace_observed",
    "owner_only_and_cross_workspace_denials_distinct",
    "fake_google_or_postgresql_not_used_for_second_person",
    "membership_removal_restart_restore_observed",
    "removed_membership_relink_denied",
    "removed_membership_relink_zero_partial_state_observed",
    "old_session_remained_denied_after_restore",
    "all_successful_relinks_preserved_subject_user_and_created_new_session",
    "operator_membership_actions_service_attributed",
    "operator_never_attributed_as_owner_user",
    "denials_returned_no_semantic_result_or_partial_state",
    "exact_audit_lineage_observed",
    "no_sensitive_material_in_source",
}
_REVIEWER_SOURCE_ATTESTATIONS = {
    "read_only_reviewers_used",
    "three_distinct_reviewers_used",
    "all_reviewers_explicitly_agreed",
    "no_outstanding_blockers",
    "scoped_packet_excluded_sensitive_material",
}
_COMPLETION_SOURCE_ATTESTATIONS = {
    "independent_read_only_auditor_used",
    "auditor_distinct_from_packet_builder",
    "all_layer_artifacts_recomputed",
    "actor_context_contract_reviewed",
    "documentation_state_reviewed",
    "reviewer_gate_and_completion_audit_are_distinct",
    "structural_rehash_not_provider_authenticity",
    "work_board_remains_authoritative",
    "no_sensitive_material_in_source",
}

_RELINK_KINDS = ("restore", "post_revocation", "post_expiry")
_REVIEW_AREAS = (
    "engineering_protocol",
    "security_governance",
    "operator_chatgpt_e2e",
)

_MCP_SEMANTIC_RESULTS: dict[str, int] = {}
_LIVE_SEMANTIC_RESULTS = {
    "first_owner_whoami": 1,
    "first_owner_open_upload_session": 1,
    "second_real_google_user_whoami": 1,
    "restored_session_whoami": 1,
    "post_revocation_relinked_whoami": 1,
    "post_expiry_relinked_whoami": 1,
}
_LIVE_DENIAL_EVENTS = {
    "second_user_owner_only_action_denied",
    "second_user_cross_workspace_action_denied",
    "mcp_identity_forgery_denied",
    "removed_membership_old_token_denied",
    "removed_membership_old_token_denied_after_restart",
    "removed_membership_relink_denied",
    "removed_old_session_still_denied_after_restore",
    "revoked_token_denied",
    "expired_token_denied",
}

_SERVICE_AUDIT_EVENTS = {
    "owner_bootstrap_created_service",
    "second_user_invitation_created_service",
    "second_user_owner_only_denied",
    "second_user_membership_removed_service",
    "second_user_membership_restored_service",
    "restored_session_revoked_service",
}


class EvidencePacketError(RuntimeError):
    """Safe operator-facing error with no path or private value."""

    def __init__(self, code: str, blockers: Sequence[str] = ()) -> None:
        self.code = code if _SAFE_LABEL_RE.fullmatch(code) else "evidence_packet_invalid"
        self.blockers = tuple(_safe_blocker(value) for value in blockers)
        super().__init__(self.code)


def source_templates() -> dict[str, dict[str, Any]]:
    """Return incomplete, leak-safe templates for all governed human sources."""

    return {
        "mcp_inspector": _mcp_source_template(),
        "live_chatgpt_google": _chatgpt_source_template(),
        "reviewer_gate": _reviewer_source_template(),
        "completion_audit": _completion_source_template(),
    }


def validate_mcp_inspector_source(source: Any) -> dict[str, Any]:
    blockers: list[str] = []
    value = _mapping(source, "mcp_source_not_object", blockers)
    _validate_exact_keys(value, _MCP_SOURCE_FIELDS, "mcp_source_keys_mismatch", blockers)
    _validate_common_source_header(
        value,
        artifact_type=_MCP_SOURCE_TYPE,
        blockers=blockers,
        prefix="mcp",
    )
    if value.get("endpoint_scheme") != "https":
        blockers.append("mcp_remote_https_required")
    _validate_required_hash(
        value.get("inspector_version_hash"), "mcp_inspector_version_hash_invalid", blockers
    )
    _validate_required_hash(
        value.get("negotiated_protocol_version_hash"),
        "mcp_protocol_version_hash_invalid",
        blockers,
    )
    events = _validate_events(
        value.get("events"),
        expected_names=tuple(_authority._MCP_INSPECTOR_SEQUENCE),
        semantic_results=_MCP_SEMANTIC_RESULTS,
        prefix="mcp",
        blockers=blockers,
    )
    _validate_attestations(
        value.get("attestations"),
        _MCP_SOURCE_ATTESTATIONS,
        "mcp",
        blockers,
    )
    if events:
        for event in events:
            if (
                event.get("semantic_result_count") != 0
                or event.get("partial_state_write_count") != 0
            ):
                blockers.append("mcp_semantic_result_or_partial_state_violation")
                break
    _validate_no_forbidden_material(value, "mcp", blockers)
    return _source_validation_result(value, blockers)


def validate_live_chatgpt_google_source(source: Any) -> dict[str, Any]:
    blockers: list[str] = []
    value = _mapping(source, "live_source_not_object", blockers)
    _validate_exact_keys(value, _CHATGPT_SOURCE_FIELDS, "live_source_keys_mismatch", blockers)
    _validate_common_source_header(
        value,
        artifact_type=_CHATGPT_SOURCE_TYPE,
        blockers=blockers,
        prefix="live",
    )
    if value.get("endpoint_scheme") != "https":
        blockers.append("live_public_https_required")
    if value.get("callback_bootstrap_mode") not in {
        "direct_exact_callback",
        "reserved_invalid_discovery",
    }:
        blockers.append("live_callback_bootstrap_mode_invalid")
    _validate_required_hash(
        value.get("negotiated_protocol_version_hash"),
        "live_protocol_version_hash_invalid",
        blockers,
    )
    identities = _validate_identities(value.get("identities"), blockers)
    relinks = _validate_relink_bindings(value.get("relink_bindings"), identities, blockers)
    events = _validate_events(
        value.get("events"),
        expected_names=tuple(_authority._LIVE_CHATGPT_GOOGLE_SEQUENCE),
        semantic_results=_LIVE_SEMANTIC_RESULTS,
        prefix="live",
        blockers=blockers,
    )
    _validate_audit_records(value.get("audit_records"), blockers)
    _validate_attestations(
        value.get("attestations"),
        _CHATGPT_SOURCE_ATTESTATIONS,
        "live",
        blockers,
    )
    if events:
        denial_hashes = [
            _event(events, name).get("observation_commitment_hash")
            for name in (
                "second_user_owner_only_action_denied",
                "second_user_cross_workspace_action_denied",
                "mcp_identity_forgery_denied",
            )
        ]
        if len(set(denial_hashes)) != len(denial_hashes):
            blockers.append("live_denial_evidence_merged")
        for name in _LIVE_DENIAL_EVENTS:
            event = _event(events, name)
            if (
                event.get("semantic_result_count") != 0
                or event.get("partial_state_write_count") != 0
            ):
                blockers.append("live_denial_zero_state_violation")
                break
        zero_event = _event(events, "removed_membership_relink_zero_partial_state_verified")
        if (
            zero_event.get("semantic_result_count") != 0
            or zero_event.get("partial_state_write_count") != 0
        ):
            blockers.append("live_removed_relink_zero_state_violation")
    if identities and relinks:
        member = identities["member"]
        expected_prior = member["initial_session_binding_hash"]
        seen_sessions = {
            identities["owner"]["initial_session_binding_hash"],
            expected_prior,
        }
        for relink in relinks:
            if relink.get("prior_session_binding_hash") != expected_prior:
                blockers.append("live_relink_prior_session_chain_mismatch")
            new_session = relink.get("new_session_binding_hash")
            if new_session in seen_sessions:
                blockers.append("live_relink_new_session_not_distinct")
            if _is_real_hash(new_session):
                seen_sessions.add(str(new_session))
                expected_prior = str(new_session)
    _validate_no_forbidden_material(value, "live", blockers)
    return _source_validation_result(value, blockers)


def validate_reviewer_gate_source(
    source: Any,
    *,
    expected_review_packet_hash: str | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    value = _mapping(source, "reviewer_source_not_object", blockers)
    _validate_exact_keys(
        value,
        _REVIEWER_SOURCE_FIELDS,
        "reviewer_source_keys_mismatch",
        blockers,
    )
    _validate_common_source_header(
        value,
        artifact_type=_REVIEWER_SOURCE_TYPE,
        blockers=blockers,
        prefix="reviewer",
    )
    _validate_required_hash(
        value.get("review_packet_commitment_hash"),
        "reviewer_packet_commitment_hash_invalid",
        blockers,
    )
    if value.get("closure_transition_plan_hash") != _authority._CLOSURE_TRANSITION_PLAN_HASH:
        blockers.append("reviewer_closure_transition_plan_mismatch")
    if value.get("reviewer_gate_governance_hash") != (
        _authority._repository_contract_hash(
            _authority._REVIEWER_GATE_GOVERNANCE_PATHS,
        )
    ):
        blockers.append("reviewer_gate_governance_hash_mismatch")
    if (
        expected_review_packet_hash is not None
        and value.get("review_packet_commitment_hash") != expected_review_packet_hash
    ):
        blockers.append("reviewer_review_packet_stale")
    reviewers = value.get("reviewers")
    if not isinstance(reviewers, list):
        blockers.append("reviewer_entries_not_list")
        reviewer_values: list[dict[str, Any]] = []
    else:
        reviewer_values = [item for item in reviewers if isinstance(item, dict)]
        if len(reviewer_values) != 3 or len(reviewer_values) != len(reviewers):
            blockers.append("reviewer_exact_three_required")
    ids: list[str] = []
    outputs: list[str] = []
    for index, reviewer in enumerate(reviewer_values, start=1):
        _validate_exact_keys(
            reviewer,
            _REVIEWER_FIELDS,
            "reviewer_entry_keys_mismatch",
            blockers,
        )
        if reviewer.get("sequence_index") != index:
            blockers.append("reviewer_sequence_invalid")
        if reviewer.get("review_area") != _REVIEW_AREAS[index - 1]:
            blockers.append("reviewer_area_order_invalid")
        if reviewer.get("decision") != "AGREE":
            blockers.append("reviewer_agreement_missing")
        if reviewer.get("blocking_finding_count") != 0:
            blockers.append("reviewer_blocking_finding_present")
        for field, code in (
            ("reviewer_id_hash", "reviewer_id_hash_invalid"),
            ("output_commitment_hash", "reviewer_output_commitment_hash_invalid"),
        ):
            _validate_required_hash(reviewer.get(field), code, blockers)
        if _is_real_hash(reviewer.get("reviewer_id_hash")):
            ids.append(str(reviewer["reviewer_id_hash"]))
        if _is_real_hash(reviewer.get("output_commitment_hash")):
            outputs.append(str(reviewer["output_commitment_hash"]))
    if len(ids) != len(set(ids)):
        blockers.append("reviewer_ids_not_distinct")
    if len(outputs) != len(set(outputs)):
        blockers.append("reviewer_outputs_not_distinct")
    _validate_attestations(
        value.get("attestations"),
        _REVIEWER_SOURCE_ATTESTATIONS,
        "reviewer",
        blockers,
    )
    _validate_no_forbidden_material(value, "reviewer", blockers)
    return _source_validation_result(value, blockers)


def validate_completion_audit_source(
    source: Any,
    *,
    expected_local_receipt: Mapping[str, Any] | None = None,
    expected_layer_artifacts: Mapping[str, str] | None = None,
    expected_operator_execution_authority_pin_hash: str | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    blockers: list[str] = []
    value = _mapping(source, "completion_source_not_object", blockers)
    _validate_exact_keys(
        value,
        _COMPLETION_SOURCE_FIELDS,
        "completion_source_keys_mismatch",
        blockers,
    )
    if value.get("artifact_type") != _COMPLETION_SOURCE_TYPE:
        blockers.append("completion_source_type_mismatch")
    if value.get("schema_version") != _SOURCE_SCHEMA_VERSION:
        blockers.append("completion_source_schema_version_mismatch")
    if value.get("status") != "passed":
        blockers.append("completion_source_not_passed")
    if value.get("auditor_attested") is not True:
        blockers.append("completion_auditor_attestation_missing")
    if value.get("operator_attested") is not True:
        blockers.append("completion_operator_attestation_missing")
    for field, code in (
        ("independent_auditor_id_hash", "completion_auditor_id_hash_invalid"),
        ("audit_output_commitment_hash", "completion_audit_output_hash_invalid"),
        ("implementation_contract_hash", "completion_implementation_hash_invalid"),
        ("local_harness_report_hash", "completion_local_harness_hash_invalid"),
        ("actor_context_contract_hash", "completion_actor_context_hash_invalid"),
        ("documentation_contract_hash", "completion_documentation_hash_invalid"),
        (
            "closure_transition_plan_hash",
            "completion_closure_transition_plan_hash_invalid",
        ),
        (
            "reviewer_gate_governance_hash",
            "completion_reviewer_gate_governance_hash_invalid",
        ),
        (
            "operator_execution_authority_pin_hash",
            "completion_operator_authority_pin_hash_invalid",
        ),
        (
            "reviewed_layer_artifact_set_hash",
            "completion_layer_artifact_set_hash_invalid",
        ),
    ):
        _validate_required_hash(value.get(field), code, blockers)
    if value.get("blocking_finding_count") != 0:
        blockers.append("completion_blocking_finding_present")
    journeys = value.get("journeys")
    if not isinstance(journeys, list):
        blockers.append("completion_journeys_not_list")
        journey_values: list[dict[str, Any]] = []
    else:
        journey_values = [item for item in journeys if isinstance(item, dict)]
        if len(journey_values) != len(journeys):
            blockers.append("completion_journey_not_object")
    expected_names = list(_authority._ISSUE20_COMPLETION_JOURNEYS)
    names = [journey.get("journey_name") for journey in journey_values]
    if len(names) < len(expected_names):
        blockers.append("completion_journey_missing")
    if len(names) > len(set(names)):
        blockers.append("completion_journey_duplicate")
    if names != expected_names:
        if len(names) == len(expected_names) and set(names) == set(expected_names):
            blockers.append("completion_journey_out_of_order")
        else:
            blockers.append("completion_journey_manifest_mismatch")
    journey_hashes: list[str] = []
    for index, journey in enumerate(journey_values, start=1):
        _validate_exact_keys(
            journey,
            _COMPLETION_JOURNEY_FIELDS,
            "completion_journey_fields_mismatch",
            blockers,
        )
        if journey.get("sequence_index") != index:
            blockers.append("completion_journey_sequence_invalid")
        if journey.get("status") != "passed":
            blockers.append("completion_journey_not_passed")
        _validate_required_hash(
            journey.get("evidence_commitment_hash"),
            "completion_journey_evidence_hash_invalid",
            blockers,
        )
        if _is_real_hash(journey.get("evidence_commitment_hash")):
            journey_hashes.append(str(journey["evidence_commitment_hash"]))
    if len(journey_hashes) != len(set(journey_hashes)):
        blockers.append("completion_journey_evidence_not_distinct")
    _validate_attestations(
        value.get("attestations"),
        _COMPLETION_SOURCE_ATTESTATIONS,
        "completion",
        blockers,
    )
    if value.get("implementation_contract_hash") != (
        _authority.issue20_implementation_contract_hash(root)
    ):
        blockers.append("completion_implementation_contract_stale")
    if value.get("actor_context_contract_hash") != _authority._repository_contract_hash(
        _authority._ACTOR_CONTEXT_CONTRACT_PATHS,
        root=root,
    ):
        blockers.append("completion_actor_context_contract_stale")
    if value.get("documentation_contract_hash") != _authority._repository_contract_hash(
        _authority._DOCUMENTATION_CONTRACT_PATHS,
        root=root,
    ):
        blockers.append("completion_documentation_contract_stale")
    if value.get("closure_transition_plan_hash") != _authority._CLOSURE_TRANSITION_PLAN_HASH:
        blockers.append("completion_closure_transition_plan_mismatch")
    if value.get("reviewer_gate_governance_hash") != (
        _authority._repository_contract_hash(
            _authority._REVIEWER_GATE_GOVERNANCE_PATHS,
            root=root,
        )
    ):
        blockers.append("completion_reviewer_gate_governance_stale")
    if expected_local_receipt is not None:
        for source_field, receipt_field in (
            ("implementation_contract_hash", "implementation_contract_hash"),
            ("local_harness_report_hash", "local_completion_audit_report_hash"),
            ("actor_context_contract_hash", "actor_context_contract_hash"),
            ("documentation_contract_hash", "documentation_contract_hash"),
        ):
            if value.get(source_field) != expected_local_receipt.get(receipt_field):
                blockers.append(f"completion_{source_field}_mismatch")
    if expected_layer_artifacts is not None and value.get(
        "reviewed_layer_artifact_set_hash"
    ) != _reviewed_layer_artifact_set_hash(expected_layer_artifacts):
        blockers.append("completion_reviewed_layer_artifact_set_mismatch")
    if (
        expected_operator_execution_authority_pin_hash is not None
        and value.get("operator_execution_authority_pin_hash")
        != expected_operator_execution_authority_pin_hash
    ):
        blockers.append("completion_operator_authority_pin_hash_mismatch")
    _validate_no_forbidden_material(value, "completion", blockers)
    return _source_validation_result(value, blockers)


def validate_governed_sources(
    *,
    mcp_inspector: Any,
    live_chatgpt_google: Any,
    reviewer_gate: Any,
    completion_audit: Any,
) -> dict[str, Any]:
    validations = {
        "mcp_inspector": validate_mcp_inspector_source(mcp_inspector),
        "live_chatgpt_google": validate_live_chatgpt_google_source(live_chatgpt_google),
        "reviewer_gate": validate_reviewer_gate_source(reviewer_gate),
        "completion_audit": validate_completion_audit_source(completion_audit),
    }
    blockers = [
        f"{name}_{blocker}"
        for name, validation in validations.items()
        for blocker in validation["blockers"]
    ]
    return {
        "artifact_type": "issue20_governed_source_validation_v1",
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
        "blockers": blockers,
        "source_artifact_hashes": {
            name: validation["source_artifact_hash"] for name, validation in validations.items()
        },
        "source_statuses": {name: validation["status"] for name, validation in validations.items()},
    }


def _build_external_packet_from_validated_inputs(
    *,
    local_receipt: Mapping[str, Any],
    live_postgresql_layer: Mapping[str, Any],
    operator_cli_postgresql_layer: Mapping[str, Any],
    operator_cli_postgresql_execution_authority_pin: Mapping[str, Any],
    production_container_lifecycle_layer: Mapping[str, Any],
    mcp_inspector_source: Mapping[str, Any],
    live_chatgpt_google_source: Mapping[str, Any],
    reviewer_gate_source: Mapping[str, Any],
    completion_audit_source: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    """Internal assembly from layers already rebuilt from their source reports."""
    _validate_existing_layer(
        "live_postgresql",
        live_postgresql_layer,
        _live_postgresql.validate_live_postgresql_external_layer,
    )
    _validate_existing_layer(
        "operator_cli_postgresql",
        operator_cli_postgresql_layer,
        lambda layer: _authority.validate_operator_cli_postgresql_external_layer(
            layer,
            trusted_execution_authority_pin=(operator_cli_postgresql_execution_authority_pin),
        ),
    )
    _validate_existing_layer(
        "production_container_lifecycle",
        production_container_lifecycle_layer,
        _authority.validate_production_container_lifecycle_external_layer,
    )
    mcp_layer = _build_mcp_inspector_layer(mcp_inspector_source)
    chatgpt_layer = _build_live_chatgpt_google_layer(live_chatgpt_google_source)
    local = _validated_local_receipt(local_receipt, root=root)
    core_layers: dict[str, dict[str, Any]] = {
        "live_postgresql": dict(live_postgresql_layer),
        "operator_cli_postgresql": dict(operator_cli_postgresql_layer),
        "production_container_lifecycle": dict(production_container_lifecycle_layer),
        "mcp_inspector": mcp_layer,
        "live_chatgpt_google": chatgpt_layer,
    }
    review_packet = _core_evidence_review_packet(
        local_receipt=local,
        core_layers=core_layers,
        mcp_inspector_source_hash=_source_hash(mcp_inspector_source),
        live_chatgpt_google_source_hash=_source_hash(live_chatgpt_google_source),
    )
    reviewer_layer = _build_reviewer_gate_layer(
        reviewer_gate_source,
        expected_review_packet_hash=_source_hash(review_packet),
    )
    layers = {**core_layers, "reviewer_gate": reviewer_layer}
    layer_artifacts = {name: layer["evidence_artifact_hash"] for name, layer in layers.items()}
    completion_validation = validate_completion_audit_source(
        completion_audit_source,
        expected_local_receipt=local,
        expected_layer_artifacts=layer_artifacts,
        expected_operator_execution_authority_pin_hash=_authority.sha256_json(
            dict(operator_cli_postgresql_execution_authority_pin)
        ),
        root=root,
    )
    _raise_source_validation("completion_audit", completion_validation)
    journeys = completion_audit_source["journeys"]
    completion_without_artifact = {
        "status": "passed",
        "operator_attested": completion_audit_source["operator_attested"],
        "source_evidence_artifact_hash": completion_validation["source_artifact_hash"],
        "implementation_contract_hash": completion_audit_source["implementation_contract_hash"],
        "local_harness_report_hash": completion_audit_source["local_harness_report_hash"],
        "live_postgresql_artifact_hash": layer_artifacts["live_postgresql"],
        "operator_cli_postgresql_artifact_hash": layer_artifacts["operator_cli_postgresql"],
        "operator_execution_authority_pin_hash": _authority.sha256_json(
            dict(operator_cli_postgresql_execution_authority_pin)
        ),
        "production_container_lifecycle_artifact_hash": layer_artifacts[
            "production_container_lifecycle"
        ],
        "mcp_inspector_artifact_hash": layer_artifacts["mcp_inspector"],
        "live_chatgpt_google_artifact_hash": layer_artifacts["live_chatgpt_google"],
        "reviewer_gate_artifact_hash": layer_artifacts["reviewer_gate"],
        "actor_context_contract_hash": completion_audit_source["actor_context_contract_hash"],
        "documentation_contract_hash": completion_audit_source["documentation_contract_hash"],
        "journey_manifest_hash": local["issue20_completion_journey_manifest_hash"],
        "journey_count": len(journeys),
        "passed_journey_count": sum(journey.get("status") == "passed" for journey in journeys),
        "missing_journey_count": max(
            0, len(_authority._ISSUE20_COMPLETION_JOURNEYS) - len(journeys)
        ),
        "blocking_finding_count": completion_audit_source["blocking_finding_count"],
        "attestations": {
            "independent_completion_audit_used": True,
            "all_layer_artifacts_recomputed": True,
            "actor_context_contract_reviewed": True,
            "documentation_state_reviewed": True,
            "work_board_remains_authoritative": True,
            "no_sensitive_material_in_packet": True,
        },
    }
    completion_layer = _authority.build_completion_audit_external_layer(completion_without_artifact)
    if not completion_layer:
        raise EvidencePacketError("completion_audit_layer_build_failed")
    layers["completion_audit"] = completion_layer
    packet = {
        "packet_type": _authority._EXTERNAL_PACKET_TYPE,
        "schema_version": _authority._EXTERNAL_PACKET_SCHEMA_VERSION,
        "layers": layers,
    }
    validation = _authority.validate_external_evidence_packet(
        packet,
        expected_local_harness_report_hash=local["local_completion_audit_report_hash"],
        expected_operator_execution_authority_pin=(operator_cli_postgresql_execution_authority_pin),
        root=root,
    )
    if validation.get("passed") is not True:
        raise EvidencePacketError(
            "authority_packet_validation_failed",
            tuple(validation.get("blockers", ())),
        )
    return packet


def build_external_packet(
    *,
    local_harness_report: Mapping[str, Any],
    live_postgresql_evidence: Mapping[str, Any],
    operator_cli_postgresql_report: Mapping[str, Any],
    operator_cli_postgresql_execution_authority: Mapping[str, Any],
    operator_cli_postgresql_execution_authority_pin: Mapping[str, Any],
    production_container_lifecycle_reports: Sequence[Mapping[str, Any]],
    operator_attest_postgresql: bool,
    operator_attest_lifecycle: bool,
    mcp_inspector_source: Mapping[str, Any],
    live_chatgpt_google_source: Mapping[str, Any],
    reviewer_gate_source: Mapping[str, Any],
    completion_audit_source: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    local_receipt = validate_local_harness_report(local_harness_report, root=root)
    live_layer = validated_live_postgresql_report_layer(live_postgresql_evidence)
    operator_layer = _operator_layer_from_report(
        operator_cli_postgresql_report,
        operator_attested=operator_attest_postgresql,
        trusted_execution_authority=operator_cli_postgresql_execution_authority,
        trusted_execution_authority_pin=(operator_cli_postgresql_execution_authority_pin),
    )
    lifecycle_layer = _lifecycle_layer_from_reports(
        production_container_lifecycle_reports,
        operator_attested=operator_attest_lifecycle,
    )
    return _build_external_packet_from_validated_inputs(
        local_receipt=local_receipt,
        live_postgresql_layer=live_layer,
        operator_cli_postgresql_layer=operator_layer,
        operator_cli_postgresql_execution_authority_pin=(
            operator_cli_postgresql_execution_authority_pin
        ),
        production_container_lifecycle_layer=lifecycle_layer,
        mcp_inspector_source=mcp_inspector_source,
        live_chatgpt_google_source=live_chatgpt_google_source,
        reviewer_gate_source=reviewer_gate_source,
        completion_audit_source=completion_audit_source,
        root=root,
    )


def prepare_reviewer_materials(
    *,
    local_harness_report: Mapping[str, Any],
    live_postgresql_evidence: Mapping[str, Any],
    operator_cli_postgresql_report: Mapping[str, Any],
    operator_cli_postgresql_execution_authority: Mapping[str, Any],
    operator_cli_postgresql_execution_authority_pin: Mapping[str, Any],
    production_container_lifecycle_reports: Sequence[Mapping[str, Any]],
    operator_attest_postgresql: bool,
    operator_attest_lifecycle: bool,
    mcp_inspector_source: Mapping[str, Any],
    live_chatgpt_google_source: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, dict[str, Any]]:
    local = validate_local_harness_report(local_harness_report, root=root)
    core_layers = {
        "live_postgresql": validated_live_postgresql_report_layer(live_postgresql_evidence),
        "operator_cli_postgresql": _operator_layer_from_report(
            operator_cli_postgresql_report,
            operator_attested=operator_attest_postgresql,
            trusted_execution_authority=operator_cli_postgresql_execution_authority,
            trusted_execution_authority_pin=(operator_cli_postgresql_execution_authority_pin),
        ),
        "production_container_lifecycle": _lifecycle_layer_from_reports(
            production_container_lifecycle_reports,
            operator_attested=operator_attest_lifecycle,
        ),
        "mcp_inspector": _build_mcp_inspector_layer(mcp_inspector_source),
        "live_chatgpt_google": _build_live_chatgpt_google_layer(live_chatgpt_google_source),
    }
    review_packet = _core_evidence_review_packet(
        local_receipt=local,
        core_layers=core_layers,
        mcp_inspector_source_hash=_source_hash(mcp_inspector_source),
        live_chatgpt_google_source_hash=_source_hash(live_chatgpt_google_source),
    )
    reviewer_source = _reviewer_source_template()
    reviewer_source["review_packet_commitment_hash"] = _source_hash(review_packet)
    return {
        "core-review-packet.json": review_packet,
        "reviewer-gate-source.json": reviewer_source,
    }


def prepare_completion_audit_source(
    *,
    local_harness_report: Mapping[str, Any],
    live_postgresql_evidence: Mapping[str, Any],
    operator_cli_postgresql_report: Mapping[str, Any],
    operator_cli_postgresql_execution_authority: Mapping[str, Any],
    operator_cli_postgresql_execution_authority_pin: Mapping[str, Any],
    production_container_lifecycle_reports: Sequence[Mapping[str, Any]],
    operator_attest_postgresql: bool,
    operator_attest_lifecycle: bool,
    mcp_inspector_source: Mapping[str, Any],
    live_chatgpt_google_source: Mapping[str, Any],
    reviewer_gate_source: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    local = validate_local_harness_report(local_harness_report, root=root)
    core_layers = {
        "live_postgresql": validated_live_postgresql_report_layer(live_postgresql_evidence),
        "operator_cli_postgresql": _operator_layer_from_report(
            operator_cli_postgresql_report,
            operator_attested=operator_attest_postgresql,
            trusted_execution_authority=operator_cli_postgresql_execution_authority,
            trusted_execution_authority_pin=(operator_cli_postgresql_execution_authority_pin),
        ),
        "production_container_lifecycle": _lifecycle_layer_from_reports(
            production_container_lifecycle_reports,
            operator_attested=operator_attest_lifecycle,
        ),
        "mcp_inspector": _build_mcp_inspector_layer(mcp_inspector_source),
        "live_chatgpt_google": _build_live_chatgpt_google_layer(live_chatgpt_google_source),
    }
    review_packet = _core_evidence_review_packet(
        local_receipt=local,
        core_layers=core_layers,
        mcp_inspector_source_hash=_source_hash(mcp_inspector_source),
        live_chatgpt_google_source_hash=_source_hash(live_chatgpt_google_source),
    )
    reviewer_layer = _build_reviewer_gate_layer(
        reviewer_gate_source,
        expected_review_packet_hash=_source_hash(review_packet),
    )
    all_layers = {**core_layers, "reviewer_gate": reviewer_layer}
    layer_artifacts = {
        name: str(layer["evidence_artifact_hash"]) for name, layer in all_layers.items()
    }
    source = _completion_source_template()
    source.update(
        {
            "implementation_contract_hash": local["implementation_contract_hash"],
            "local_harness_report_hash": local["local_completion_audit_report_hash"],
            "actor_context_contract_hash": local["actor_context_contract_hash"],
            "documentation_contract_hash": local["documentation_contract_hash"],
            "operator_execution_authority_pin_hash": _authority.sha256_json(
                dict(operator_cli_postgresql_execution_authority_pin)
            ),
            "reviewed_layer_artifact_set_hash": _reviewed_layer_artifact_set_hash(layer_artifacts),
        }
    )
    return source


def validate_local_harness_report(
    report: Mapping[str, Any], *, root: Path = ROOT
) -> dict[str, str]:
    if not isinstance(report, Mapping):
        raise EvidencePacketError("local_harness_report_invalid")
    validation = _authority.validate_report(dict(report))
    if validation.get("passed") is not True or report.get("status") != "passed":
        raise EvidencePacketError("local_harness_report_invalid")
    claims = report.get("claim_boundary")
    if (
        not isinstance(claims, Mapping)
        or claims.get("supports_external_evidence_packet_contract_claim") is not False
    ):
        raise EvidencePacketError("local_harness_report_must_be_local_only")
    safe_outputs = report.get("safe_outputs")
    if not isinstance(safe_outputs, Mapping):
        raise EvidencePacketError("local_harness_safe_outputs_missing")
    receipt = {
        "implementation_contract_hash": _authority.issue20_implementation_contract_hash(root),
        "local_completion_audit_report_hash": safe_outputs.get(
            "local_completion_audit_report_hash"
        ),
        "actor_context_contract_hash": safe_outputs.get("actor_context_contract_hash"),
        "documentation_contract_hash": safe_outputs.get("documentation_contract_hash"),
        "issue20_completion_journey_manifest_hash": safe_outputs.get(
            "issue20_completion_journey_manifest_hash"
        ),
    }
    return _validated_local_receipt(receipt, root=root)


def validated_live_postgresql_report_layer(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise EvidencePacketError("live_postgresql_evidence_invalid")
    value = dict(evidence)
    if "live_postgresql_layer" not in value:
        raise EvidencePacketError("live_postgresql_source_report_required")
    validation = _live_postgresql.validate_report(value)
    if validation.get("passed") is not True or value.get("status") != "passed":
        raise EvidencePacketError("live_postgresql_report_invalid")
    layer = value.get("live_postgresql_layer")
    if not isinstance(layer, Mapping):
        raise EvidencePacketError("live_postgresql_layer_missing")
    _validate_existing_layer(
        "live_postgresql",
        layer,
        _live_postgresql.validate_live_postgresql_external_layer,
    )
    return dict(layer)


def _operator_layer_from_report(
    report: Mapping[str, Any],
    *,
    operator_attested: bool,
    trusted_execution_authority: Mapping[str, Any],
    trusted_execution_authority_pin: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise EvidencePacketError("operator_evidence_report_invalid")
    try:
        return _authority.build_operator_cli_postgresql_external_layer(
            report,
            operator_attested=operator_attested,
            trusted_execution_authority=trusted_execution_authority,
            trusted_execution_authority_pin=trusted_execution_authority_pin,
        )
    except _authority.OperatorEvidenceError as error:
        raise EvidencePacketError(error.code) from error


def _lifecycle_layer_from_reports(
    reports: Sequence[Mapping[str, Any]],
    *,
    operator_attested: bool,
) -> dict[str, Any]:
    try:
        return _authority.aggregate_production_container_lifecycle_reports(
            reports,
            operator_attested=operator_attested,
        )
    except _authority.LifecycleEvidenceError as error:
        raise EvidencePacketError(error.code) from error


def validate_current_packet(
    packet: Mapping[str, Any],
    *,
    local_harness_report: Mapping[str, Any],
    live_postgresql_evidence: Mapping[str, Any],
    operator_cli_postgresql_report: Mapping[str, Any],
    operator_cli_postgresql_execution_authority: Mapping[str, Any],
    operator_cli_postgresql_execution_authority_pin: Mapping[str, Any],
    production_container_lifecycle_reports: Sequence[Mapping[str, Any]],
    operator_attest_postgresql: bool,
    operator_attest_lifecycle: bool,
    mcp_inspector_source: Mapping[str, Any],
    live_chatgpt_google_source: Mapping[str, Any],
    reviewer_gate_source: Mapping[str, Any],
    completion_audit_source: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    expected_packet = build_external_packet(
        local_harness_report=local_harness_report,
        live_postgresql_evidence=live_postgresql_evidence,
        operator_cli_postgresql_report=operator_cli_postgresql_report,
        operator_cli_postgresql_execution_authority=(operator_cli_postgresql_execution_authority),
        operator_cli_postgresql_execution_authority_pin=(
            operator_cli_postgresql_execution_authority_pin
        ),
        production_container_lifecycle_reports=production_container_lifecycle_reports,
        operator_attest_postgresql=operator_attest_postgresql,
        operator_attest_lifecycle=operator_attest_lifecycle,
        mcp_inspector_source=mcp_inspector_source,
        live_chatgpt_google_source=live_chatgpt_google_source,
        reviewer_gate_source=reviewer_gate_source,
        completion_audit_source=completion_audit_source,
        root=root,
    )
    local = validate_local_harness_report(local_harness_report, root=root)
    validation = _authority.validate_external_evidence_packet(
        packet,
        expected_local_harness_report_hash=local["local_completion_audit_report_hash"],
        expected_operator_execution_authority_pin=(operator_cli_postgresql_execution_authority_pin),
        root=root,
    )
    exact_rebuild_match = dict(packet) == expected_packet
    blockers = [_safe_blocker(value) for value in validation.get("blockers", ())]
    if not exact_rebuild_match:
        blockers.append("packet_source_rebuild_mismatch")
    passed = validation.get("passed") is True and exact_rebuild_match
    return {
        "artifact_type": "issue20_external_packet_authority_validation_v1",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "packet_hash": validation.get("packet_hash", _authority._MISSING_HASH),
        "expected_packet_hash": _authority.sha256_json(expected_packet),
        "exact_source_rebuild_match": exact_rebuild_match,
        "layer_statuses": validation.get("layer_statuses", {}),
        "layer_artifact_hashes": validation.get("layer_artifact_hashes", {}),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    template_parser = subparsers.add_parser("template")
    template_parser.add_argument("--output-dir", type=Path, required=True)

    sources_parser = subparsers.add_parser("validate-sources")
    _add_source_arguments(sources_parser)
    sources_parser.add_argument("--output", type=Path, required=True)

    review_parser = subparsers.add_parser("prepare-reviewer-source")
    _add_core_evidence_arguments(review_parser)
    review_parser.add_argument("--output-dir", type=Path, required=True)

    completion_parser = subparsers.add_parser("prepare-completion-audit-source")
    _add_core_evidence_arguments(completion_parser)
    completion_parser.add_argument("--reviewer-gate-source", type=Path, required=True)
    completion_parser.add_argument("--output", type=Path, required=True)

    build_parser = subparsers.add_parser("build-packet")
    _add_core_evidence_arguments(build_parser)
    build_parser.add_argument("--reviewer-gate-source", type=Path, required=True)
    build_parser.add_argument("--completion-audit-source", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)

    packet_parser = subparsers.add_parser("validate-packet")
    packet_parser.add_argument("--packet", type=Path, required=True)
    _add_core_evidence_arguments(packet_parser)
    packet_parser.add_argument("--reviewer-gate-source", type=Path, required=True)
    packet_parser.add_argument("--completion-audit-source", type=Path, required=True)
    packet_parser.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "template":
            return _template_command(args.output_dir)
        if args.command == "validate-sources":
            result = validate_governed_sources(
                mcp_inspector=_read_json(args.mcp_inspector_source),
                live_chatgpt_google=_read_json(args.live_chatgpt_google_source),
                reviewer_gate=_read_json(args.reviewer_gate_source),
                completion_audit=_read_json(args.completion_audit_source),
            )
            _write_json(args.output, result)
            return 0 if result["status"] == "passed" else 1
        if args.command == "prepare-reviewer-source":
            materials = prepare_reviewer_materials(
                local_harness_report=_read_json(args.local_harness_report),
                live_postgresql_evidence=_read_json(args.live_postgresql_evidence),
                operator_cli_postgresql_report=_read_json(args.operator_cli_postgresql_report),
                operator_cli_postgresql_execution_authority=_read_json(
                    args.operator_cli_postgresql_execution_authority
                ),
                operator_cli_postgresql_execution_authority_pin=_read_json(
                    args.operator_cli_postgresql_execution_authority_pin
                ),
                production_container_lifecycle_reports=[
                    _read_json(path) for path in args.production_container_lifecycle_report
                ],
                operator_attest_postgresql=args.operator_attest_postgresql,
                operator_attest_lifecycle=args.operator_attest_lifecycle,
                mcp_inspector_source=_read_json(args.mcp_inspector_source),
                live_chatgpt_google_source=_read_json(args.live_chatgpt_google_source),
            )
            _write_atomic_directory(args.output_dir, materials)
            return 0
        if args.command == "prepare-completion-audit-source":
            source = prepare_completion_audit_source(
                local_harness_report=_read_json(args.local_harness_report),
                live_postgresql_evidence=_read_json(args.live_postgresql_evidence),
                operator_cli_postgresql_report=_read_json(args.operator_cli_postgresql_report),
                operator_cli_postgresql_execution_authority=_read_json(
                    args.operator_cli_postgresql_execution_authority
                ),
                operator_cli_postgresql_execution_authority_pin=_read_json(
                    args.operator_cli_postgresql_execution_authority_pin
                ),
                production_container_lifecycle_reports=[
                    _read_json(path) for path in args.production_container_lifecycle_report
                ],
                operator_attest_postgresql=args.operator_attest_postgresql,
                operator_attest_lifecycle=args.operator_attest_lifecycle,
                mcp_inspector_source=_read_json(args.mcp_inspector_source),
                live_chatgpt_google_source=_read_json(args.live_chatgpt_google_source),
                reviewer_gate_source=_read_json(args.reviewer_gate_source),
            )
            _write_json(args.output, source)
            return 0
        if args.command == "build-packet":
            packet = build_external_packet(
                local_harness_report=_read_json(args.local_harness_report),
                live_postgresql_evidence=_read_json(args.live_postgresql_evidence),
                operator_cli_postgresql_report=_read_json(args.operator_cli_postgresql_report),
                operator_cli_postgresql_execution_authority=_read_json(
                    args.operator_cli_postgresql_execution_authority
                ),
                operator_cli_postgresql_execution_authority_pin=_read_json(
                    args.operator_cli_postgresql_execution_authority_pin
                ),
                production_container_lifecycle_reports=[
                    _read_json(path) for path in args.production_container_lifecycle_report
                ],
                operator_attest_postgresql=args.operator_attest_postgresql,
                operator_attest_lifecycle=args.operator_attest_lifecycle,
                mcp_inspector_source=_read_json(args.mcp_inspector_source),
                live_chatgpt_google_source=_read_json(args.live_chatgpt_google_source),
                reviewer_gate_source=_read_json(args.reviewer_gate_source),
                completion_audit_source=_read_json(args.completion_audit_source),
            )
            _write_json(args.output, packet)
            return 0
        if args.command == "validate-packet":
            result = validate_current_packet(
                _read_json(args.packet),
                local_harness_report=_read_json(args.local_harness_report),
                live_postgresql_evidence=_read_json(args.live_postgresql_evidence),
                operator_cli_postgresql_report=_read_json(args.operator_cli_postgresql_report),
                operator_cli_postgresql_execution_authority=_read_json(
                    args.operator_cli_postgresql_execution_authority
                ),
                operator_cli_postgresql_execution_authority_pin=_read_json(
                    args.operator_cli_postgresql_execution_authority_pin
                ),
                production_container_lifecycle_reports=[
                    _read_json(path) for path in args.production_container_lifecycle_report
                ],
                operator_attest_postgresql=args.operator_attest_postgresql,
                operator_attest_lifecycle=args.operator_attest_lifecycle,
                mcp_inspector_source=_read_json(args.mcp_inspector_source),
                live_chatgpt_google_source=_read_json(args.live_chatgpt_google_source),
                reviewer_gate_source=_read_json(args.reviewer_gate_source),
                completion_audit_source=_read_json(args.completion_audit_source),
            )
            _write_json(args.output, result)
            return 0 if result["passed"] else 1
    except EvidencePacketError as error:
        safe_error = {
            "artifact_type": "issue20_external_evidence_cli_error_v1",
            "status": "failed",
            "error_code": error.code,
            "blocker_count": len(error.blockers),
            "blockers": list(error.blockers),
        }
        output = getattr(args, "output", None)
        generation_commands = {
            "prepare-reviewer-source",
            "prepare-completion-audit-source",
            "build-packet",
        }
        safe_error_written = False
        if isinstance(output, Path) and args.command not in generation_commands:
            try:
                _write_json(output, safe_error)
                safe_error_written = True
            except EvidencePacketError:
                pass
        if not safe_error_written:
            print(json.dumps(safe_error, sort_keys=True, separators=(",", ":")))
        return 1
    raise EvidencePacketError("unsupported_command")


def _mcp_source_template() -> dict[str, Any]:
    return {
        "artifact_type": _MCP_SOURCE_TYPE,
        "schema_version": _SOURCE_SCHEMA_VERSION,
        "status": "incomplete",
        "operator_attested": False,
        "endpoint_scheme": "https",
        "inspector_version_hash": _TEMPLATE_HASH,
        "negotiated_protocol_version_hash": _TEMPLATE_HASH,
        "events": _event_templates(
            tuple(_authority._MCP_INSPECTOR_SEQUENCE),
            _MCP_SEMANTIC_RESULTS,
        ),
        "attestations": {name: False for name in sorted(_MCP_SOURCE_ATTESTATIONS)},
    }


def _chatgpt_source_template() -> dict[str, Any]:
    audit_records: list[dict[str, Any]] = []
    for index, event_name in enumerate(_authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE, start=1):
        service_actor = event_name in _SERVICE_AUDIT_EVENTS
        owner_only_probe = event_name == "second_user_owner_only_denied"
        audit_records.append(
            {
                "sequence_index": index,
                "event_name": event_name,
                "action": "oauth_invitation_create" if owner_only_probe else event_name,
                "status": "denied" if "denied" in event_name else "passed",
                "reason_code": (
                    "invitation_owner_required"
                    if owner_only_probe
                    else "policy_denied"
                    if "denied" in event_name
                    else "observed"
                ),
                "actor_type": "service" if service_actor else "user",
                "actor_user_binding_hash": (
                    _ABSENT_VALUE_COMMITMENT if service_actor else _TEMPLATE_HASH
                ),
                "actor_service_binding_hash": (
                    _TEMPLATE_HASH if service_actor else _ABSENT_VALUE_COMMITMENT
                ),
                "approval_user_binding_hash": (
                    _TEMPLATE_HASH if owner_only_probe else _ABSENT_VALUE_COMMITMENT
                ),
                "workspace_binding_hash": _TEMPLATE_HASH,
                "external_identity_binding_hash": _TEMPLATE_HASH,
                "oauth_client_binding_hash": _TEMPLATE_HASH,
                "oauth_token_session_binding_hash": _TEMPLATE_HASH,
                "request_binding_hash": _TEMPLATE_HASH,
                "tool_call_binding_hash": (
                    _ABSENT_VALUE_COMMITMENT if owner_only_probe else _TEMPLATE_HASH
                ),
                "metadata_shape_hash": _TEMPLATE_HASH,
                "previous_audit_record_hash": (
                    _ABSENT_VALUE_COMMITMENT if index == 1 else _TEMPLATE_HASH
                ),
                "audit_record_hash": _TEMPLATE_HASH,
            }
        )
    return {
        "artifact_type": _CHATGPT_SOURCE_TYPE,
        "schema_version": _SOURCE_SCHEMA_VERSION,
        "status": "incomplete",
        "operator_attested": False,
        "endpoint_scheme": "https",
        "callback_bootstrap_mode": "pending",
        "negotiated_protocol_version_hash": _TEMPLATE_HASH,
        "identities": {
            "owner": {
                "external_subject_commitment_hash": _TEMPLATE_HASH,
                "formowl_user_binding_hash": _TEMPLATE_HASH,
                "external_identity_binding_hash": _TEMPLATE_HASH,
                "workspace_binding_hash": _TEMPLATE_HASH,
                "role": "owner",
                "initial_session_binding_hash": _TEMPLATE_HASH,
            },
            "member": {
                "external_subject_commitment_hash": _TEMPLATE_HASH,
                "formowl_user_binding_hash": _TEMPLATE_HASH,
                "external_identity_binding_hash": _TEMPLATE_HASH,
                "workspace_binding_hash": _TEMPLATE_HASH,
                "role": "member",
                "initial_session_binding_hash": _TEMPLATE_HASH,
            },
        },
        "relink_bindings": [
            {
                "sequence_index": index,
                "relink_kind": kind,
                "external_subject_commitment_hash": _TEMPLATE_HASH,
                "formowl_user_binding_hash": _TEMPLATE_HASH,
                "prior_session_binding_hash": _TEMPLATE_HASH,
                "new_session_binding_hash": _TEMPLATE_HASH,
            }
            for index, kind in enumerate(_RELINK_KINDS, start=1)
        ],
        "events": _event_templates(
            tuple(_authority._LIVE_CHATGPT_GOOGLE_SEQUENCE),
            _LIVE_SEMANTIC_RESULTS,
        ),
        "audit_records": audit_records,
        "attestations": {name: False for name in sorted(_CHATGPT_SOURCE_ATTESTATIONS)},
    }


def _reviewer_source_template() -> dict[str, Any]:
    return {
        "artifact_type": _REVIEWER_SOURCE_TYPE,
        "schema_version": _SOURCE_SCHEMA_VERSION,
        "status": "incomplete",
        "operator_attested": False,
        "closure_transition_plan_hash": _authority._CLOSURE_TRANSITION_PLAN_HASH,
        "reviewer_gate_governance_hash": _authority._repository_contract_hash(
            _authority._REVIEWER_GATE_GOVERNANCE_PATHS,
        ),
        "review_packet_commitment_hash": _TEMPLATE_HASH,
        "reviewers": [
            {
                "sequence_index": index,
                "reviewer_id_hash": _TEMPLATE_HASH,
                "review_area": area,
                "decision": "PENDING",
                "output_commitment_hash": _TEMPLATE_HASH,
                "blocking_finding_count": 0,
            }
            for index, area in enumerate(_REVIEW_AREAS, start=1)
        ],
        "attestations": {name: False for name in sorted(_REVIEWER_SOURCE_ATTESTATIONS)},
    }


def _completion_source_template() -> dict[str, Any]:
    return {
        "artifact_type": _COMPLETION_SOURCE_TYPE,
        "schema_version": _SOURCE_SCHEMA_VERSION,
        "status": "incomplete",
        "auditor_attested": False,
        "operator_attested": False,
        "independent_auditor_id_hash": _TEMPLATE_HASH,
        "audit_output_commitment_hash": _TEMPLATE_HASH,
        "implementation_contract_hash": _TEMPLATE_HASH,
        "local_harness_report_hash": _TEMPLATE_HASH,
        "actor_context_contract_hash": _TEMPLATE_HASH,
        "documentation_contract_hash": _TEMPLATE_HASH,
        "closure_transition_plan_hash": _authority._CLOSURE_TRANSITION_PLAN_HASH,
        "reviewer_gate_governance_hash": _authority._repository_contract_hash(
            _authority._REVIEWER_GATE_GOVERNANCE_PATHS,
        ),
        "operator_execution_authority_pin_hash": _TEMPLATE_HASH,
        "reviewed_layer_artifact_set_hash": _TEMPLATE_HASH,
        "journeys": [
            {
                "sequence_index": index,
                "journey_name": name,
                "status": "pending",
                "evidence_commitment_hash": _TEMPLATE_HASH,
            }
            for index, name in enumerate(_authority._ISSUE20_COMPLETION_JOURNEYS, start=1)
        ],
        "blocking_finding_count": 0,
        "attestations": {name: False for name in sorted(_COMPLETION_SOURCE_ATTESTATIONS)},
    }


def _event_templates(
    names: Sequence[str], semantic_results: Mapping[str, int]
) -> list[dict[str, Any]]:
    return [
        {
            "sequence_index": index,
            "event_name": name,
            "status": "pending",
            "observation_commitment_hash": _TEMPLATE_HASH,
            "semantic_result_count": semantic_results.get(name, 0),
            "partial_state_write_count": 0,
        }
        for index, name in enumerate(names, start=1)
    ]


def _build_mcp_inspector_layer(source: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_mcp_inspector_source(source)
    _raise_source_validation("mcp_inspector", validation)
    events = {item["event_name"]: item for item in source["events"]}
    value = {
        "status": "passed",
        "operator_attested": True,
        "endpoint_scheme": "https",
        "source_evidence_artifact_hash": validation["source_artifact_hash"],
        "inspector_version_hash": source["inspector_version_hash"],
        "sequence_hash": _authority.sha256_json(_authority._MCP_INSPECTOR_SEQUENCE),
        "negotiated_protocol_version_hash": source["negotiated_protocol_version_hash"],
        "public_initialize_shape_hash": events["unauthenticated_initialize_public"][
            "observation_commitment_hash"
        ],
        "public_tools_list_shape_hash": events["unauthenticated_tools_list_public"][
            "observation_commitment_hash"
        ],
        "protected_tool_challenge_hash": events["unauthenticated_protected_tool_call_challenged"][
            "observation_commitment_hash"
        ],
        "invalid_bearer_challenge_hash": events[
            "synthetic_invalid_bearer_protected_tool_call_challenged"
        ]["observation_commitment_hash"],
        **dict(_authority._MCP_INSPECTOR_EXACT_COUNTS),
        "attestations": {
            "remote_https_endpoint_observed": True,
            "real_mcp_inspector_used": True,
            "no_simulated_inspector": True,
            "public_discovery_without_oauth_observed": True,
            "protected_tool_challenge_observed": True,
            "invalid_bearer_challenge_observed": True,
            "inspector_oauth_login_not_attempted": True,
            "inspector_authenticated_journey_not_claimed": True,
            "no_raw_bearer_supplied": True,
            "no_semantic_result_or_partial_state": True,
            "no_sensitive_material_in_packet": True,
        },
    }
    layer = _authority.build_mcp_inspector_external_layer(value)
    _validate_built_layer(
        "mcp_inspector",
        layer,
        _authority.validate_mcp_inspector_external_layer,
    )
    return layer


def _build_live_chatgpt_google_layer(source: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_live_chatgpt_google_source(source)
    _raise_source_validation("live_chatgpt_google", validation)
    events = {item["event_name"]: item for item in source["events"]}
    audit_records = {item["event_name"]: item for item in source["audit_records"]}
    identities = source["identities"]
    relinks = {item["relink_kind"]: item for item in source["relink_bindings"]}

    def observation(name: str) -> str:
        return str(events[name]["observation_commitment_hash"])

    def lineage(binding_type: str, names: Sequence[str]) -> str:
        return _authority.sha256_json(
            {
                "binding_type": binding_type,
                "event_commitment_hashes": [observation(name) for name in names],
            }
        )

    value = {
        "status": "passed",
        "operator_attested": True,
        "endpoint_scheme": "https",
        "source_evidence_artifact_hash": validation["source_artifact_hash"],
        "sequence_hash": _authority.sha256_json(_authority._LIVE_CHATGPT_GOOGLE_SEQUENCE),
        "audit_lineage_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_live_chatgpt_google_audit_lineage_v1",
                "audit_records": source["audit_records"],
            }
        ),
        "audit_lineage_manifest_hash": _authority.sha256_json(
            _authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE
        ),
        "audit_lineage_field_set_hash": _authority.sha256_json(
            _authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS
        ),
        "negotiated_protocol_version_hash": source["negotiated_protocol_version_hash"],
        "public_initialize_shape_hash": observation("chatgpt_connector_discovery_initialize"),
        "public_tools_list_shape_hash": observation("chatgpt_connector_discovery_tools_list"),
        "protected_tool_challenge_hash": observation("chatgpt_protected_tool_oauth_challenge"),
        "second_user_invitation_lineage_hash": observation("second_real_google_user_invited"),
        "second_user_distinct_subject_commitment_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_two_distinct_real_google_subjects_v1",
                "owner_subject_commitment_hash": identities["owner"][
                    "external_subject_commitment_hash"
                ],
                "member_subject_commitment_hash": identities["member"][
                    "external_subject_commitment_hash"
                ],
            }
        ),
        "second_user_member_workspace_shape_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_second_user_member_workspace_shape_v1",
                "formowl_user_binding_hash": identities["member"]["formowl_user_binding_hash"],
                "workspace_binding_hash": identities["member"]["workspace_binding_hash"],
                "role": identities["member"]["role"],
            }
        ),
        "owner_only_denial_hash": observation("second_user_owner_only_action_denied"),
        "cross_workspace_denial_hash": observation("second_user_cross_workspace_action_denied"),
        "forgery_denial_hash": observation("mcp_identity_forgery_denied"),
        "membership_removal_service_audit_hash": audit_records[
            "second_user_membership_removed_service"
        ]["audit_record_hash"],
        "removed_session_revocation_state_hash": observation(
            "membership_removal_revoked_one_session"
        ),
        "removed_token_denial_hash": observation("removed_membership_old_token_denied"),
        "restart_removed_token_denial_hash": observation(
            "removed_membership_old_token_denied_after_restart"
        ),
        "removed_membership_relink_denial_hash": observation("removed_membership_relink_denied"),
        "removed_membership_relink_zero_state_hash": observation(
            "removed_membership_relink_zero_partial_state_verified"
        ),
        "membership_restore_service_audit_hash": audit_records[
            "second_user_membership_restored_service"
        ]["audit_record_hash"],
        "post_restore_old_session_denial_hash": observation(
            "removed_old_session_still_denied_after_restore"
        ),
        "restore_relink_identity_session_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_restore_relink_identity_session_v1",
                "binding": relinks["restore"],
            }
        ),
        "post_revocation_relink_identity_session_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_post_revocation_relink_identity_session_v1",
                "binding": relinks["post_revocation"],
            }
        ),
        "post_expiry_relink_identity_session_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_post_expiry_relink_identity_session_v1",
                "binding": relinks["post_expiry"],
            }
        ),
        "revocation_lineage_hash": lineage(
            "issue20_revocation_denial_relink_lineage_v1",
            (
                "restored_session_revoked",
                "revoked_token_denied",
                "same_subject_relinked_after_revocation",
                "post_revocation_relinked_whoami",
            ),
        ),
        "expiry_lineage_hash": lineage(
            "issue20_expiry_denial_relink_lineage_v1",
            (
                "relinked_token_expired",
                "expired_token_denied",
                "same_subject_relinked_after_expiry",
                "post_expiry_relinked_whoami",
            ),
        ),
        **dict(_authority._LIVE_CHATGPT_GOOGLE_EXACT_COUNTS),
        "attestations": {
            "real_chatgpt_connector_used": True,
            "live_google_login_observed": True,
            "public_https_endpoint_observed": True,
            "no_fake_google_provider": True,
            "no_simulated_chatgpt_client": True,
            "public_discovery_without_oauth_observed": True,
            "protected_tool_challenge_observed": True,
            "second_real_google_user_observed": True,
            "second_user_distinct_from_owner_observed": True,
            "second_user_member_role_and_workspace_observed": True,
            "owner_only_and_cross_workspace_denials_distinct": True,
            "fake_google_or_postgresql_not_used_for_second_person": True,
            "membership_removal_restart_restore_observed": True,
            "removed_membership_relink_denied": True,
            "removed_membership_relink_zero_partial_state_observed": True,
            "old_session_remained_denied_after_restore": True,
            "all_successful_relinks_preserved_subject_user_and_created_new_session": True,
            "operator_membership_actions_service_attributed": True,
            "operator_never_attributed_as_owner_user": True,
            "denials_returned_no_semantic_result_or_partial_state": True,
            "exact_audit_lineage_observed": True,
            "no_sensitive_material_in_packet": True,
        },
    }
    layer = _authority.build_live_chatgpt_google_external_layer(value)
    _validate_built_layer(
        "live_chatgpt_google",
        layer,
        _authority.validate_live_chatgpt_google_external_layer,
    )
    return layer


def _build_reviewer_gate_layer(
    source: Mapping[str, Any], *, expected_review_packet_hash: str
) -> dict[str, Any]:
    validation = validate_reviewer_gate_source(
        source,
        expected_review_packet_hash=expected_review_packet_hash,
    )
    _raise_source_validation("reviewer_gate", validation)
    reviewers = source["reviewers"]
    value = {
        "status": "passed",
        "operator_attested": True,
        "source_evidence_artifact_hash": validation["source_artifact_hash"],
        "reviewer_set_hash": _authority.sha256_json(
            {
                "binding_type": "issue20_reviewer_set_v1",
                "reviewers": [
                    {
                        "reviewer_id_hash": reviewer["reviewer_id_hash"],
                        "review_area": reviewer["review_area"],
                    }
                    for reviewer in reviewers
                ],
            }
        ),
        "review_packet_hash": source["review_packet_commitment_hash"],
        "reviewer_count": 3,
        "agreement_count": 3,
        "blocking_finding_count": 0,
        "attestations": {
            "read_only_reviewers_used": True,
            "no_outstanding_blockers": True,
            "scoped_packet_excluded_sensitive_material": True,
        },
    }
    layer = _authority.build_reviewer_gate_external_layer(value)
    _validate_built_layer(
        "reviewer_gate",
        layer,
        _authority.validate_reviewer_gate_external_layer,
    )
    return layer


def _validate_events(
    raw_events: Any,
    *,
    expected_names: Sequence[str],
    semantic_results: Mapping[str, int],
    prefix: str,
    blockers: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_events, list):
        blockers.append(f"{prefix}_events_not_list")
        return []
    events = [item for item in raw_events if isinstance(item, dict)]
    if len(events) != len(raw_events):
        blockers.append(f"{prefix}_event_not_object")
    names = [item.get("event_name") for item in events]
    expected = list(expected_names)
    if len(names) < len(expected):
        blockers.append(f"{prefix}_event_missing")
    if len(names) > len(set(names)):
        blockers.append(f"{prefix}_event_duplicate")
    if names != expected:
        if len(names) == len(expected) and set(names) == set(expected):
            blockers.append(f"{prefix}_event_out_of_order")
        else:
            blockers.append(f"{prefix}_event_manifest_mismatch")
    observation_hashes: list[str] = []
    for index, event in enumerate(events, start=1):
        _validate_exact_keys(
            event,
            _EVENT_FIELDS,
            f"{prefix}_event_keys_mismatch",
            blockers,
        )
        name = event.get("event_name")
        if event.get("sequence_index") != index:
            blockers.append(f"{prefix}_event_sequence_invalid")
        if event.get("status") != "passed":
            blockers.append(f"{prefix}_event_not_passed")
        _validate_required_hash(
            event.get("observation_commitment_hash"),
            f"{prefix}_event_commitment_hash_invalid",
            blockers,
        )
        if _is_real_hash(event.get("observation_commitment_hash")):
            observation_hashes.append(str(event["observation_commitment_hash"]))
        expected_semantic = semantic_results.get(str(name), 0)
        if event.get("semantic_result_count") != expected_semantic:
            blockers.append(f"{prefix}_event_semantic_result_count_invalid")
        if event.get("partial_state_write_count") != 0:
            blockers.append(f"{prefix}_event_partial_state_write_count_invalid")
    if len(observation_hashes) != len(set(observation_hashes)):
        blockers.append(f"{prefix}_event_commitments_not_distinct")
    return events


def _validate_identities(raw: Any, blockers: list[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, Mapping):
        blockers.append("live_identities_not_object")
        return {}
    identities = dict(raw)
    _validate_exact_keys(identities, {"owner", "member"}, "live_identity_keys_mismatch", blockers)
    result: dict[str, dict[str, Any]] = {}
    for name, role in (("owner", "owner"), ("member", "member")):
        identity = identities.get(name)
        if not isinstance(identity, Mapping):
            blockers.append("live_identity_not_object")
            continue
        value = dict(identity)
        _validate_exact_keys(value, _IDENTITY_FIELDS, "live_identity_fields_mismatch", blockers)
        if value.get("role") != role:
            blockers.append("live_identity_role_invalid")
        for field in _IDENTITY_FIELDS - {"role"}:
            _validate_required_hash(
                value.get(field),
                "live_identity_binding_hash_invalid",
                blockers,
            )
        result[name] = value
    if set(result) == {"owner", "member"}:
        owner = result["owner"]
        member = result["member"]
        if owner["external_subject_commitment_hash"] == member["external_subject_commitment_hash"]:
            blockers.append("live_real_google_subjects_not_distinct")
        if owner["formowl_user_binding_hash"] == member["formowl_user_binding_hash"]:
            blockers.append("live_formowl_users_not_distinct")
        if owner["external_identity_binding_hash"] == member["external_identity_binding_hash"]:
            blockers.append("live_external_identities_not_distinct")
        if owner["workspace_binding_hash"] != member["workspace_binding_hash"]:
            blockers.append("live_owner_member_workspace_binding_mismatch")
        if owner["initial_session_binding_hash"] == member["initial_session_binding_hash"]:
            blockers.append("live_initial_sessions_not_distinct")
    return result


def _validate_relink_bindings(
    raw: Any,
    identities: Mapping[str, Mapping[str, Any]],
    blockers: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        blockers.append("live_relink_bindings_not_list")
        return []
    relinks = [item for item in raw if isinstance(item, dict)]
    if len(relinks) != 3 or len(relinks) != len(raw):
        blockers.append("live_exact_three_relinks_required")
    member = identities.get("member", {})
    for index, relink in enumerate(relinks, start=1):
        _validate_exact_keys(
            relink,
            _RELINK_FIELDS,
            "live_relink_fields_mismatch",
            blockers,
        )
        if relink.get("sequence_index") != index:
            blockers.append("live_relink_sequence_invalid")
        if index <= len(_RELINK_KINDS) and relink.get("relink_kind") != _RELINK_KINDS[index - 1]:
            blockers.append("live_relink_order_invalid")
        for field in _RELINK_FIELDS - {"sequence_index", "relink_kind"}:
            _validate_required_hash(
                relink.get(field),
                "live_relink_binding_hash_invalid",
                blockers,
            )
        if member:
            if relink.get("external_subject_commitment_hash") != member.get(
                "external_subject_commitment_hash"
            ):
                blockers.append("live_relink_subject_changed")
            if relink.get("formowl_user_binding_hash") != member.get("formowl_user_binding_hash"):
                blockers.append("live_relink_formowl_user_changed")
    return relinks


def _validate_audit_records(raw: Any, blockers: list[str]) -> None:
    if not isinstance(raw, list):
        blockers.append("live_audit_records_not_list")
        return
    records = [item for item in raw if isinstance(item, dict)]
    if len(records) != len(raw):
        blockers.append("live_audit_record_not_object")
    expected_names = list(_authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE)
    names = [record.get("event_name") for record in records]
    if len(names) < len(expected_names):
        blockers.append("live_audit_record_missing")
    if len(names) > len(set(names)):
        blockers.append("live_audit_record_duplicate")
    if names != expected_names:
        if len(names) == len(expected_names) and set(names) == set(expected_names):
            blockers.append("live_audit_record_out_of_order")
        else:
            blockers.append("live_audit_manifest_mismatch")
    record_hashes: list[str] = []
    previous_hash = _ABSENT_VALUE_COMMITMENT
    hash_fields = {
        field
        for field in _authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS
        if field.endswith("_hash")
    }
    for index, record in enumerate(records, start=1):
        _validate_exact_keys(
            record,
            set(_authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS),
            "live_audit_record_fields_mismatch",
            blockers,
        )
        if record.get("sequence_index") != index:
            blockers.append("live_audit_record_sequence_invalid")
        event_name = record.get("event_name")
        for field in ("event_name", "action", "reason_code", "actor_type"):
            if not isinstance(record.get(field), str) or not _SAFE_LABEL_RE.fullmatch(
                str(record.get(field))
            ):
                blockers.append("live_audit_label_invalid")
        expected_status = "denied" if "denied" in str(event_name) else "passed"
        if record.get("status") != expected_status:
            blockers.append("live_audit_status_invalid")
        if record.get("actor_type") not in {"user", "service", "external_unauthenticated"}:
            blockers.append("live_audit_actor_type_invalid")
        service_event = event_name in _SERVICE_AUDIT_EVENTS
        if service_event:
            if record.get("actor_type") != "service":
                blockers.append("live_service_audit_actor_invalid")
            if record.get("actor_user_binding_hash") != _ABSENT_VALUE_COMMITMENT:
                blockers.append("live_service_audit_user_attribution_present")
            if not _is_real_hash(record.get("actor_service_binding_hash")):
                blockers.append("live_service_audit_binding_missing")
        if event_name == "second_user_owner_only_denied":
            if record.get("action") != "oauth_invitation_create":
                blockers.append("live_owner_only_probe_action_invalid")
            if record.get("reason_code") != "invitation_owner_required":
                blockers.append("live_owner_only_probe_reason_invalid")
            if not _is_real_hash(record.get("approval_user_binding_hash")):
                blockers.append("live_owner_only_member_attribution_missing")
            if record.get("tool_call_binding_hash") != _ABSENT_VALUE_COMMITMENT:
                blockers.append("live_owner_only_probe_must_not_claim_mcp_tool")
        for field in hash_fields:
            value = record.get(field)
            allow_absent = field != "audit_record_hash" and (
                field != "previous_audit_record_hash" or index == 1
            )
            if not _is_real_hash(value) and not (
                allow_absent and value == _ABSENT_VALUE_COMMITMENT
            ):
                blockers.append("live_audit_binding_hash_invalid")
        if record.get("previous_audit_record_hash") != previous_hash:
            blockers.append("live_audit_hash_chain_broken")
        audit_hash = record.get("audit_record_hash")
        if audit_hash != _safe_audit_record_hash(record):
            blockers.append("live_audit_record_commitment_mismatch")
        if _is_real_hash(audit_hash):
            record_hashes.append(str(audit_hash))
            previous_hash = str(audit_hash)
    if len(record_hashes) != 47:
        blockers.append("live_exact_47_audit_hashes_required")
    if len(record_hashes) != len(set(record_hashes)):
        blockers.append("live_audit_record_hashes_not_distinct")


def _validate_common_source_header(
    value: Mapping[str, Any],
    *,
    artifact_type: str,
    blockers: list[str],
    prefix: str,
) -> None:
    if value.get("artifact_type") != artifact_type:
        blockers.append(f"{prefix}_source_type_mismatch")
    if value.get("schema_version") != _SOURCE_SCHEMA_VERSION:
        blockers.append(f"{prefix}_source_schema_version_mismatch")
    if value.get("status") != "passed":
        blockers.append(f"{prefix}_source_not_passed")
    if value.get("operator_attested") is not True:
        blockers.append(f"{prefix}_operator_attestation_missing")


def _validate_attestations(
    raw: Any,
    expected: set[str],
    prefix: str,
    blockers: list[str],
) -> None:
    if not isinstance(raw, Mapping):
        blockers.append(f"{prefix}_attestations_not_object")
        return
    attestations = dict(raw)
    _validate_exact_keys(
        attestations,
        expected,
        f"{prefix}_attestation_keys_mismatch",
        blockers,
    )
    if any(attestations.get(name) is not True for name in expected):
        blockers.append(f"{prefix}_attestation_missing")


def _validate_no_forbidden_material(value: Any, prefix: str, blockers: list[str]) -> None:
    violation = False

    def walk(item: Any) -> None:
        nonlocal violation
        if isinstance(item, Mapping):
            for key, child in item.items():
                normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
                if not isinstance(child, bool):
                    if normalized in {
                        "path",
                        "url",
                        "endpoint_url",
                        "raw_payload",
                        "payload",
                        "transcript",
                        "email",
                        "subject",
                        "sql",
                        "token",
                        "credential",
                    }:
                        violation = True
                    if not normalized.endswith(("_hash", "_count")) and any(
                        part in normalized for part in _SENSITIVE_KEY_PARTS
                    ):
                        violation = True
                walk(child)
            return
        if isinstance(item, list):
            for child in item:
                walk(child)
            return
        if isinstance(item, str) and any(
            pattern.search(item)
            for pattern in (
                _URL_RE,
                _EMAIL_RE,
                _JWT_RE,
                _BEARER_RE,
                _RAW_PATH_RE,
                _SQL_RE,
                _PRIVATE_KEY_RE,
            )
        ):
            violation = True

    walk(value)
    try:
        _authority.assert_safe_harness_report(value)
    except AssertionError:
        violation = True
    if violation:
        blockers.append(f"{prefix}_source_contains_forbidden_material")


def _source_validation_result(value: Mapping[str, Any], blockers: Sequence[str]) -> dict[str, Any]:
    unique_blockers = list(dict.fromkeys(_safe_blocker(item) for item in blockers))
    return {
        "passed": not unique_blockers,
        "status": "passed" if not unique_blockers else "failed",
        "blocker_count": len(unique_blockers),
        "blockers": unique_blockers,
        "source_artifact_hash": (
            _source_hash(value) if not unique_blockers else _authority._MISSING_HASH
        ),
    }


def _validated_local_receipt(receipt: Mapping[str, Any], *, root: Path) -> dict[str, str]:
    expected = {
        "implementation_contract_hash",
        "local_completion_audit_report_hash",
        "actor_context_contract_hash",
        "documentation_contract_hash",
        "issue20_completion_journey_manifest_hash",
    }
    if set(receipt) != expected:
        raise EvidencePacketError("local_harness_receipt_keys_mismatch")
    value = {key: str(receipt.get(key)) for key in expected}
    if any(not _is_real_hash(item) for item in value.values()):
        raise EvidencePacketError("local_harness_receipt_hash_invalid")
    if value["implementation_contract_hash"] != _authority.issue20_implementation_contract_hash(
        root
    ):
        raise EvidencePacketError("local_implementation_contract_mismatch")
    if value["actor_context_contract_hash"] != _authority._repository_contract_hash(
        _authority._ACTOR_CONTEXT_CONTRACT_PATHS,
        root=root,
    ):
        raise EvidencePacketError("local_actor_context_contract_mismatch")
    if value["documentation_contract_hash"] != _authority._repository_contract_hash(
        _authority._DOCUMENTATION_CONTRACT_PATHS,
        root=root,
    ):
        raise EvidencePacketError("local_documentation_contract_mismatch")
    if value["issue20_completion_journey_manifest_hash"] != _authority.sha256_json(
        _authority._ISSUE20_COMPLETION_JOURNEYS
    ):
        raise EvidencePacketError("local_journey_manifest_mismatch")
    return value


def _validate_existing_layer(
    name: str,
    layer: Mapping[str, Any],
    validator: Any,
) -> None:
    if not isinstance(layer, Mapping):
        raise EvidencePacketError(f"{name}_layer_invalid")
    validation = validator(dict(layer))
    if validation.get("passed") is not True:
        raise EvidencePacketError(f"{name}_layer_invalid")


def _validate_built_layer(name: str, layer: Any, validator: Any) -> None:
    if not isinstance(layer, Mapping) or validator(layer).get("passed") is not True:
        raise EvidencePacketError(f"{name}_public_layer_build_failed")


def _raise_source_validation(name: str, validation: Mapping[str, Any]) -> None:
    if validation.get("passed") is not True:
        raise EvidencePacketError(
            f"{name}_source_invalid",
            tuple(validation.get("blockers", ())),
        )


def _event(events: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    for event in events:
        if event.get("event_name") == name:
            return event
    return {}


def _mapping(value: Any, code: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(code)
        return {}
    return dict(value)


def _validate_exact_keys(
    value: Mapping[str, Any], expected: set[str], code: str, blockers: list[str]
) -> None:
    if set(value) != expected:
        blockers.append(code)


def _validate_required_hash(value: Any, code: str, blockers: list[str]) -> None:
    if not _is_real_hash(value):
        blockers.append(code)


def _is_real_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _SHA256_RE.fullmatch(value) is not None
        and value not in {_TEMPLATE_HASH, _authority._MISSING_HASH, _ABSENT_VALUE_COMMITMENT}
    )


def _source_hash(value: Mapping[str, Any]) -> str:
    return _authority.sha256_json(
        {
            "binding_type": "issue20_governed_safe_source_artifact_v1",
            "artifact": value,
        }
    )


def _core_evidence_review_packet(
    *,
    local_receipt: Mapping[str, str],
    core_layers: Mapping[str, Mapping[str, Any]],
    mcp_inspector_source_hash: str,
    live_chatgpt_google_source_hash: str,
) -> dict[str, Any]:
    expected_layers = {
        "live_postgresql",
        "operator_cli_postgresql",
        "production_container_lifecycle",
        "mcp_inspector",
        "live_chatgpt_google",
    }
    if set(core_layers) != expected_layers:
        raise EvidencePacketError("core_review_layer_set_invalid")
    packet = {
        "artifact_type": "issue20_core_evidence_review_packet_v1",
        "schema_version": 1,
        "status": "ready_for_review",
        "local_receipt": dict(local_receipt),
        "core_layer_statuses": {
            name: layer.get("status") for name, layer in sorted(core_layers.items())
        },
        "core_layer_artifact_hashes": {
            name: layer.get("evidence_artifact_hash") for name, layer in sorted(core_layers.items())
        },
        "governed_source_artifact_hashes": {
            "mcp_inspector": mcp_inspector_source_hash,
            "live_chatgpt_google": live_chatgpt_google_source_hash,
        },
        "completion_journey_manifest_hash": _authority.sha256_json(
            _authority._ISSUE20_COMPLETION_JOURNEYS
        ),
        "closure_transition_plan_hash": _authority._CLOSURE_TRANSITION_PLAN_HASH,
        "reviewer_gate_governance_hash": _authority._repository_contract_hash(
            _authority._REVIEWER_GATE_GOVERNANCE_PATHS,
        ),
        "claim_boundary": {
            "supports_issue20_closure_claim": False,
            "supports_production_ready_claim": False,
            "requires_reviewer_gate": True,
            "requires_independent_completion_audit": True,
        },
    }
    try:
        _authority.assert_safe_harness_report(packet)
    except AssertionError as error:
        raise EvidencePacketError("core_review_packet_unsafe") from error
    return packet


def _reviewed_layer_artifact_set_hash(layer_artifacts: Mapping[str, str]) -> str:
    expected_names = {
        "live_postgresql",
        "operator_cli_postgresql",
        "production_container_lifecycle",
        "mcp_inspector",
        "live_chatgpt_google",
        "reviewer_gate",
    }
    if set(layer_artifacts) != expected_names or any(
        not _is_real_hash(value) for value in layer_artifacts.values()
    ):
        return _authority._MISSING_HASH
    return _authority.sha256_json(
        {
            "binding_type": "issue20_reviewed_layer_artifact_set_v1",
            "layer_artifacts": dict(sorted(layer_artifacts.items())),
        }
    )


def _safe_audit_record_hash(record: Mapping[str, Any]) -> str:
    """Bind every public safe-row field, including the previous-row hash."""

    return _authority.sha256_json(
        {
            "binding_type": "issue20_live_chatgpt_google_safe_audit_record_v1",
            "record_without_audit_record_hash": {
                field: record.get(field)
                for field in _authority._LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS
                if field != "audit_record_hash"
            },
        }
    )


def _safe_blocker(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return normalized[:96] if _SAFE_LABEL_RE.fullmatch(normalized[:96]) else "evidence_invalid"


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--mcp-inspector-source", type=Path, required=True)
    parser.add_argument("--live-chatgpt-google-source", type=Path, required=True)
    parser.add_argument("--reviewer-gate-source", type=Path, required=True)
    parser.add_argument("--completion-audit-source", type=Path, required=True)


def _add_core_evidence_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--local-harness-report", type=Path, required=True)
    parser.add_argument("--live-postgresql-evidence", type=Path, required=True)
    parser.add_argument("--operator-cli-postgresql-report", type=Path, required=True)
    parser.add_argument(
        "--operator-cli-postgresql-execution-authority",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--operator-cli-postgresql-execution-authority-pin",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--production-container-lifecycle-report",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--operator-attest-postgresql", action="store_true")
    parser.add_argument("--operator-attest-lifecycle", action="store_true")
    parser.add_argument("--mcp-inspector-source", type=Path, required=True)
    parser.add_argument("--live-chatgpt-google-source", type=Path, required=True)


def _template_command(output_dir: Path) -> int:
    names = {
        "mcp_inspector": "mcp-inspector-source.json",
        "live_chatgpt_google": "live-chatgpt-google-source.json",
        "reviewer_gate": "reviewer-gate-source.json",
        "completion_audit": "completion-audit-source.json",
    }
    _write_atomic_directory(
        output_dir,
        {filename: source_templates()[key] for key, filename in names.items()},
    )
    print(
        json.dumps(
            {
                "artifact_type": "issue20_governed_source_templates_v1",
                "status": "created",
                "template_count": len(names),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _write_atomic_directory(
    output_dir: Path,
    files: Mapping[str, Mapping[str, Any]],
) -> None:
    staging: Path | None = None
    try:
        output_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.path.lexists(output_dir):
            raise EvidencePacketError("template_output_exists")
        if output_dir.parent.is_symlink():
            raise EvidencePacketError("template_output_parent_untrusted")
        parent_metadata = output_dir.parent.stat()
        if parent_metadata.st_uid != os.getuid() or parent_metadata.st_mode & 0o022:
            raise EvidencePacketError("template_output_parent_untrusted")
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{output_dir.name}.staging.",
                dir=output_dir.parent,
            )
        )
        staging.chmod(0o700)
    except OSError as error:
        raise EvidencePacketError("template_output_directory_unavailable") from error
    try:
        for filename, value in files.items():
            if Path(filename).name != filename:
                raise EvidencePacketError("atomic_output_filename_invalid")
            _write_json(staging / filename, value)
        if os.path.lexists(output_dir):
            raise EvidencePacketError("template_output_exists")
        os.rename(staging, output_dir)
        staging = None
    except (OSError, EvidencePacketError) as error:
        if isinstance(error, EvidencePacketError):
            raise
        raise EvidencePacketError("template_output_unavailable") from error
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidencePacketError("evidence_input_invalid") from error
    if not isinstance(value, dict):
        raise EvidencePacketError("evidence_input_not_object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    except OSError as error:
        raise EvidencePacketError("evidence_output_unavailable") from error


if __name__ == "__main__":
    raise SystemExit(main())
