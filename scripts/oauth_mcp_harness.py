#!/usr/bin/env python3
"""Run or validate the deterministic issue #20 OAuth and remote MCP harness.

The primary gate uses a fake Google provider and a simulated ChatGPT public
OAuth client over real local HTTP. It is intentionally not evidence of a live
Google account, public HTTPS deployment, MCP Inspector run, or ChatGPT linking.
External packets validate bounded hash/status/count evidence only; this harness
keeps pre-closure evidence separate from the post-audit completion-state
transition that decides whole-issue closure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROOT = Path(__file__).resolve().parents[1]
for import_root in (ROOT / "python", ROOT / "tests", ROOT / "scripts"):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import connected_runtime_container_lifecycle_probe as _lifecycle_probe  # noqa: E402
import connected_operator_postgres_live_journey as _operator_journey  # noqa: E402
import connected_runtime_postgres_live_e2e as _live_postgresql  # noqa: E402
from formowl_core import write_json_atomic  # noqa: E402
from formowl_evidence import issue20_implementation_contract_hash  # noqa: E402
from oauth_harness import (  # noqa: E402
    ISSUE20_BASE_COMMIT,
    assert_safe_harness_report,
    load_function_harness_manifest,
    run_function_harness_test_suite,
    run_issue20_deterministic_e2e,
    sha256_json,
    validate_function_harness_execution,
    validate_function_harness_manifest,
)


DEFAULT_OUTPUT = Path(tempfile.gettempdir()) / "formowl-issue20-oauth-mcp-harness.json"
_OUTPUT_WRITE_ERROR = {
    "artifact_type": "issue20_external_evidence_cli_error_v1",
    "error_code": "output_write_failed",
    "status": "failed",
}
_FINALIZATION_BUILD_REJECTED = {
    "artifact_type": "issue20_finalization_cli_validation_v1",
    "status": "failed",
    "passed": False,
    "blocker_count": 1,
}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LIFECYCLE_EXTERNAL_HASH_FIELDS = (
    "runtime_image_contract_hash",
    "compose_runtime_wiring_hash",
    "compose_live_journey_hash",
    "compose_live_security_contract_hash",
    "compose_secret_snapshot_set_hash",
    "oauth_seed_state_hash",
    "first_client_result_hash",
    "restart_client_result_hash",
    "persistent_core_state_hash",
    "readiness_shape_hash",
    "jwks_phase_set_hash",
    "runtime_log_hash",
)
_LIFECYCLE_STABLE_HASH_FIELDS = (
    "implementation_contract_hash",
    "runtime_image_contract_hash",
    "compose_runtime_wiring_hash",
    "migration_initial_result_hash",
    "migration_restart_result_hash",
    "oauth_seed_state_hash",
    "readiness_shape_hash",
    "jwks_phase_set_hash",
    "runtime_security_contract_hash",
    "runtime_log_hash",
    "data_restart_state_hash",
    "command_contract_hash",
)
_LIFECYCLE_EXTERNAL_COUNT_SOURCES = {
    "compose_healthcheck_success_count": "compose_healthcheck_success_count",
    "compose_migration_success_count": "compose_migration_success_count",
    "compose_old_snapshot_retirement_count": "compose_old_snapshot_retirement_count",
    "compose_postgres_0400_secret_read_count": "compose_postgres_0400_secret_read_count",
    "compose_preflight_success_count": "compose_preflight_success_count",
    "compose_runtime_ready_count": "compose_runtime_ready_count",
    "compose_secret_snapshot_count": "compose_secret_snapshot_count",
    "operator_owned_0400_secret_count": "operator_owned_0400_secret_count",
    "compose_service_count": "compose_service_count",
    "runtime_process_start_count": "runtime_process_start_count",
    "runtime_ready_count": "runtime_ready_count",
    "sigterm_clean_exit_count": "sigterm_clean_exit_count",
    "database_release_count": "database_release_count",
    "bearer_whoami_success_count": "bearer_whoami_success_count",
    "upload_session_count": "persisted_upload_session_count",
    "forgery_denial_count": "bearer_expected_denial_count",
    "persisted_user_count": "persisted_user_count",
    "persisted_external_identity_count": "persisted_external_identity_count",
    "persisted_token_session_count": "persisted_token_session_count",
    "persisted_file_audit_count": "persisted_file_audit_count",
    "postgres_mcp_allowed_audit_count": "postgres_mcp_allowed_audit_count",
    "postgres_mcp_denied_audit_count": "postgres_mcp_denied_audit_count",
    "persisted_state_snapshot_count": "persisted_state_snapshot_count",
    "jwks_initial_public_key_count": "jwks_initial_public_key_count",
    "jwks_overlap_public_key_count": "jwks_overlap_public_key_count",
    "jwks_retired_public_key_count": "jwks_retired_public_key_count",
}

_OPERATOR_SOURCE_SCHEMA_VERSION = 2
_OPERATOR_EXTERNAL_LAYER_BINDING_TYPE = "operator_cli_postgresql_external_layer_v2"
_LIFECYCLE_EXTERNAL_LAYER_BINDING_TYPE = "production_container_lifecycle_external_layer_v4"
_OPERATOR_V2_OUTPUT_LABELS = {
    "bootstrap-owner",
    "invite-member",
    "lookup-owner",
    "list-users",
    "list-member-sessions-before",
    "revoke-member-session",
    "lookup-member-session-after-revoke",
    "remove-member",
    "restore-member",
    "list-member-sessions-after-restore",
    "operator-audit-contract",
    "operator-rollback-state",
}
_OPERATOR_V2_SOURCE_EXACT_COUNTS = {
    "fresh_postgresql_database_count": 1,
    "generated_secret_count": 6,
    "idempotent_secret_rerun_count": 1,
    "migration_command_success_count": 1,
    "operator_cli_success_count": 10,
    "operator_cli_denial_count": 3,
    "operator_audit_total_count": 13,
    "operator_audit_allowed_count": 10,
    "operator_audit_denied_count": 3,
    "runtime_image_build_count": 1,
    "owner_bootstrap_success_count": 1,
    "member_invitation_success_count": 1,
    "member_approval_denial_count": 1,
    "explicit_token_revocation_count": 1,
    "last_owner_removal_denial_count": 1,
    "membership_remove_success_count": 1,
    "membership_restore_success_count": 1,
    "post_restore_active_session_count": 0,
    "post_restore_inactive_session_count": 2,
    "transaction_rollback_probe_count": 1,
    "transaction_rollback_preserved_state_count": 1,
}
_OPERATOR_V2_SOURCE_ATTESTATIONS = {
    "actual_connected_cli_executed",
    "clean_temporary_secret_set_used",
    "current_runtime_image_built_from_worktree",
    "fresh_postgresql_database_used",
    "google_credential_injected_outside_initializer",
    "inside_probe_used_installed_runtime_package",
    "operator_allow_and_deny_audits_persisted",
    "operator_outputs_excluded_sensitive_identity_and_backend_detail",
    "report_contains_only_safe_status_count_and_hash_evidence",
    "exact_operator_lifecycle_exercised",
    "member_approval_denial_audited",
    "membership_rollback_verified",
    "immutable_runtime_and_postgres_images_used",
}
_OPERATOR_LAYER_COUNT_SOURCES = {
    "runtime_image_build_count": "runtime_image_build_count",
    "fresh_database_count": "fresh_postgresql_database_count",
    "generated_secret_count": "generated_secret_count",
    "idempotent_secret_rerun_count": "idempotent_secret_rerun_count",
    "migration_success_count": "migration_command_success_count",
    "operator_cli_success_count": "operator_cli_success_count",
    "operator_cli_denial_count": "operator_cli_denial_count",
    "operator_audit_total_count": "operator_audit_total_count",
    "operator_audit_allowed_count": "operator_audit_allowed_count",
    "operator_audit_denied_count": "operator_audit_denied_count",
    "owner_bootstrap_success_count": "owner_bootstrap_success_count",
    "member_invitation_success_count": "member_invitation_success_count",
    "member_approval_denial_count": "member_approval_denial_count",
    "explicit_token_revocation_count": "explicit_token_revocation_count",
    "last_owner_removal_denial_count": "last_owner_removal_denial_count",
    "membership_remove_success_count": "membership_remove_success_count",
    "membership_restore_success_count": "membership_restore_success_count",
    "post_restore_active_session_count": "post_restore_active_session_count",
    "post_restore_inactive_session_count": "post_restore_inactive_session_count",
    "transaction_rollback_probe_count": "transaction_rollback_probe_count",
    "transaction_rollback_preserved_state_count": ("transaction_rollback_preserved_state_count"),
}
_OPERATOR_POSTGRES_IMAGE_DIGEST_HASH = sha256_json(
    {
        "binding_type": "operator_postgres_image_digest_v1",
        "pinned_image": _operator_journey.PINNED_POSTGRES_IMAGE,
    }
)
if _OPERATOR_POSTGRES_IMAGE_DIGEST_HASH != _operator_journey.POSTGRES_IMAGE_DIGEST_HASH:
    raise RuntimeError("operator PostgreSQL image authority mismatch")
_OPERATOR_V2_AUTHORITY_CONTRACT_HASH = sha256_json(
    {
        "binding_type": "operator_cli_postgresql_source_authority_v2",
        "artifact_id": _operator_journey.ARTIFACT_ID,
        "schema_version": _OPERATOR_SOURCE_SCHEMA_VERSION,
        "output_labels": sorted(_OPERATOR_V2_OUTPUT_LABELS),
        "source_counts": _OPERATOR_V2_SOURCE_EXACT_COUNTS,
        "source_attestations": sorted(_OPERATOR_V2_SOURCE_ATTESTATIONS),
        "postgres_image_digest_hash": _OPERATOR_POSTGRES_IMAGE_DIGEST_HASH,
        "execution_authority_artifact_id": (_operator_journey.EXECUTION_AUTHORITY_ARTIFACT_ID),
        "execution_authority_pin_artifact_id": (
            _operator_journey.EXECUTION_AUTHORITY_PIN_ARTIFACT_ID
        ),
        "execution_authority_pin_binding_type": (
            _operator_journey.EXECUTION_AUTHORITY_PIN_BINDING_TYPE
        ),
        "execution_receipt_artifact_id": _operator_journey.EXECUTION_RECEIPT_ARTIFACT_ID,
        "execution_receipt_binding_type": (_operator_journey.EXECUTION_RECEIPT_BINDING_TYPE),
    }
)

_EXTERNAL_LAYER_FIELDS = {
    "live_postgresql": {
        "status",
        "operator_attested",
        "endpoint_scheme",
        "evidence_artifact_hash",
        "source_report_commitment_hash",
        "implementation_contract_hash",
        "command_contract_hash",
        "schema_state_hash",
        "rollback_state_hash",
        "first_owner_bootstrap_state_hash",
        "persisted_auth_upload_audit_state_hash",
        "restart_state_hash",
        "second_user_invitation_state_hash",
        "revocation_expiry_relink_state_hash",
        "signing_key_rotation_state_hash",
        "run_count",
        "pass_count",
        "failure_count",
        "skip_count",
        "fresh_database_count",
        "migration_count",
        "first_owner_bootstrap_count",
        "persisted_auth_count",
        "persisted_upload_count",
        "persisted_audit_count",
        "restart_recovery_count",
        "second_user_invitation_count",
        "revocation_count",
        "post_relink_old_token_denial_count",
        "revoked_token_sessions_after_relink_count",
        "relink_distinct_token_session_count",
        "expiry_denial_count",
        "relink_count",
        "transaction_rollback_probe_count",
        "production_smoke_probe_count",
        "signing_key_rotation_count",
        "overlap_old_token_verification_count",
        "overlap_jwks_public_key_count",
        "new_key_token_verification_count",
        "post_overlap_old_token_denial_count",
        "post_overlap_jwks_public_key_count",
        "post_overlap_new_token_verification_count",
        "private_signing_key_exposure_count",
        "attestations",
    },
    "operator_cli_postgresql": {
        "status",
        "operator_attested",
        "endpoint_scheme",
        "evidence_artifact_hash",
        "source_schema_version",
        "implementation_contract_hash",
        "runtime_image_id_hash",
        "postgres_image_digest_hash",
        "operator_authority_contract_hash",
        "journey_script_hash",
        "journey_report_hash",
        "execution_authority_hash",
        "execution_authority_pin_hash",
        "campaign_nonce_hash",
        "receipt_public_key_hex",
        "receipt_public_key_hash",
        "unsigned_report_hash",
        "execution_receipt_payload_hash",
        "execution_receipt_signature_hex",
        "secret_initialization_contract_hash",
        "migration_result_hash",
        "operator_output_set_hash",
        "operator_audit_contract_hash",
        "operator_rollback_state_hash",
        "operator_denial_hash",
        "run_count",
        "pass_count",
        "failure_count",
        "skip_count",
        "runtime_image_build_count",
        "fresh_database_count",
        "generated_secret_count",
        "idempotent_secret_rerun_count",
        "migration_success_count",
        "operator_cli_success_count",
        "operator_cli_denial_count",
        "operator_audit_total_count",
        "operator_audit_allowed_count",
        "operator_audit_denied_count",
        "owner_bootstrap_success_count",
        "member_invitation_success_count",
        "member_approval_denial_count",
        "explicit_token_revocation_count",
        "last_owner_removal_denial_count",
        "membership_remove_success_count",
        "membership_restore_success_count",
        "post_restore_active_session_count",
        "post_restore_inactive_session_count",
        "transaction_rollback_probe_count",
        "transaction_rollback_preserved_state_count",
        "attestations",
    },
    "production_container_lifecycle": {
        "status",
        "operator_attested",
        "endpoint_scheme",
        "evidence_artifact_hash",
        "implementation_contract_hash",
        "sequence_hash",
        "run_report_set_hash",
        "runtime_image_contract_hash",
        "compose_runtime_wiring_hash",
        "compose_live_journey_hash",
        "compose_live_security_contract_hash",
        "compose_secret_snapshot_set_hash",
        "oauth_seed_state_hash",
        "first_client_result_hash",
        "restart_client_result_hash",
        "persistent_core_state_hash",
        "readiness_shape_hash",
        "jwks_phase_set_hash",
        "runtime_log_hash",
        "run_count",
        "pass_count",
        "failure_count",
        "skip_count",
        "compose_healthcheck_success_count",
        "compose_migration_success_count",
        "compose_old_snapshot_retirement_count",
        "compose_postgres_0400_secret_read_count",
        "compose_preflight_success_count",
        "compose_runtime_process_uid",
        "compose_runtime_ready_count",
        "compose_secret_snapshot_count",
        "operator_owned_0400_secret_count",
        "compose_service_count",
        "runtime_process_start_count",
        "runtime_ready_count",
        "sigterm_clean_exit_count",
        "database_release_count",
        "stateful_restart_count",
        "bearer_whoami_success_count",
        "upload_session_count",
        "forgery_denial_count",
        "persisted_user_count",
        "persisted_external_identity_count",
        "persisted_token_session_count",
        "persisted_file_audit_count",
        "postgres_mcp_allowed_audit_count",
        "postgres_mcp_denied_audit_count",
        "persisted_state_snapshot_count",
        "jwks_initial_public_key_count",
        "jwks_overlap_public_key_count",
        "jwks_retired_public_key_count",
        "runtime_process_uid",
        "attestations",
    },
    "mcp_inspector": {
        "status",
        "operator_attested",
        "endpoint_scheme",
        "evidence_artifact_hash",
        "source_evidence_artifact_hash",
        "inspector_version_hash",
        "sequence_hash",
        "negotiated_protocol_version_hash",
        "public_initialize_shape_hash",
        "public_tools_list_shape_hash",
        "protected_tool_challenge_hash",
        "invalid_bearer_challenge_hash",
        "unauthenticated_initialize_count",
        "unauthenticated_tools_list_count",
        "protected_tool_challenge_count",
        "invalid_bearer_challenge_count",
        "semantic_result_count",
        "partial_state_write_count",
        "attestations",
    },
    "live_chatgpt_google": {
        "status",
        "operator_attested",
        "endpoint_scheme",
        "evidence_artifact_hash",
        "source_evidence_artifact_hash",
        "sequence_hash",
        "audit_lineage_hash",
        "audit_lineage_manifest_hash",
        "audit_lineage_field_set_hash",
        "negotiated_protocol_version_hash",
        "public_initialize_shape_hash",
        "public_tools_list_shape_hash",
        "protected_tool_challenge_hash",
        "second_user_invitation_lineage_hash",
        "second_user_distinct_subject_commitment_hash",
        "second_user_member_workspace_shape_hash",
        "owner_only_denial_hash",
        "cross_workspace_denial_hash",
        "forgery_denial_hash",
        "membership_removal_service_audit_hash",
        "removed_session_revocation_state_hash",
        "removed_token_denial_hash",
        "restart_removed_token_denial_hash",
        "removed_membership_relink_denial_hash",
        "removed_membership_relink_zero_state_hash",
        "membership_restore_service_audit_hash",
        "post_restore_old_session_denial_hash",
        "restore_relink_identity_session_hash",
        "post_revocation_relink_identity_session_hash",
        "post_expiry_relink_identity_session_hash",
        "revocation_lineage_hash",
        "expiry_lineage_hash",
        "discovery_initialize_count",
        "discovery_tools_list_count",
        "protected_tool_challenge_count",
        "google_authorization_count",
        "google_callback_count",
        "token_exchange_count",
        "whoami_count",
        "upload_session_count",
        "second_user_invitation_count",
        "second_user_google_login_count",
        "second_user_whoami_count",
        "distinct_external_subject_count",
        "distinct_formowl_user_count",
        "second_user_member_workspace_binding_count",
        "owner_only_denial_count",
        "cross_workspace_denial_count",
        "forgery_denial_count",
        "owner_only_denial_semantic_result_count",
        "owner_only_denial_partial_state_write_count",
        "cross_workspace_denial_semantic_result_count",
        "cross_workspace_denial_partial_state_write_count",
        "forgery_denial_semantic_result_count",
        "forgery_denial_partial_state_write_count",
        "membership_removal_count",
        "membership_removal_service_audit_count",
        "removal_revoked_session_count",
        "removed_token_denial_count",
        "restart_removed_token_denial_count",
        "removed_membership_relink_denial_count",
        "removed_relink_authorization_code_issued_count",
        "removed_relink_token_session_created_count",
        "removed_relink_membership_write_count",
        "membership_restore_count",
        "membership_restore_service_audit_count",
        "owner_attributed_membership_mutation_count",
        "post_restore_old_session_denial_count",
        "restore_relink_same_subject_user_new_session_count",
        "post_revocation_relink_same_subject_user_new_session_count",
        "post_expiry_relink_same_subject_user_new_session_count",
        "revocation_count",
        "revoked_token_denial_count",
        "expiry_denial_count",
        "relink_count",
        "relinked_whoami_count",
        "audit_lineage_event_count",
        "attestations",
    },
    "reviewer_gate": {
        "status",
        "operator_attested",
        "evidence_artifact_hash",
        "source_evidence_artifact_hash",
        "reviewer_set_hash",
        "review_packet_hash",
        "reviewer_count",
        "agreement_count",
        "blocking_finding_count",
        "attestations",
    },
    "completion_audit": {
        "status",
        "operator_attested",
        "evidence_artifact_hash",
        "source_evidence_artifact_hash",
        "implementation_contract_hash",
        "local_harness_report_hash",
        "live_postgresql_artifact_hash",
        "operator_cli_postgresql_artifact_hash",
        "operator_execution_authority_pin_hash",
        "production_container_lifecycle_artifact_hash",
        "mcp_inspector_artifact_hash",
        "live_chatgpt_google_artifact_hash",
        "reviewer_gate_artifact_hash",
        "actor_context_contract_hash",
        "documentation_contract_hash",
        "journey_manifest_hash",
        "journey_count",
        "passed_journey_count",
        "missing_journey_count",
        "blocking_finding_count",
        "attestations",
    },
}

_EXTERNAL_ATTESTATIONS = {
    "live_postgresql": {
        "live_server_observed",
        "production_repository_used",
        "no_fake_database",
        "no_sensitive_material_in_packet",
    },
    "operator_cli_postgresql": {
        "actual_runtime_image_used",
        "clean_secret_bootstrap_used",
        "fresh_postgresql_used",
        "installed_runtime_package_used",
        "operator_cli_allow_and_deny_observed",
        "operator_audits_persisted",
        "exact_operator_lifecycle_observed",
        "member_approval_denial_audited",
        "membership_rollback_verified",
        "immutable_runtime_and_postgres_images_used",
        "no_sensitive_material_in_packet",
    },
    "production_container_lifecycle": {
        "actual_runtime_image_used",
        "actual_entrypoint_used",
        "actual_compose_stack_used",
        "file_mounted_secrets_used",
        "operator_owned_0400_secret_sources_observed",
        "compose_migrate_and_preflight_observed",
        "compose_secret_snapshots_and_retirement_observed",
        "runtime_uid_10001_observed",
        "jwks_one_two_one_observed",
        "real_google_preflight_observed",
        "sigterm_graceful_exit_observed",
        "stateful_restart_observed",
        "no_sensitive_material_in_packet",
    },
    "mcp_inspector": {
        "remote_https_endpoint_observed",
        "real_mcp_inspector_used",
        "no_simulated_inspector",
        "public_discovery_without_oauth_observed",
        "protected_tool_challenge_observed",
        "invalid_bearer_challenge_observed",
        "inspector_oauth_login_not_attempted",
        "inspector_authenticated_journey_not_claimed",
        "no_raw_bearer_supplied",
        "no_semantic_result_or_partial_state",
        "no_sensitive_material_in_packet",
    },
    "live_chatgpt_google": {
        "real_chatgpt_connector_used",
        "live_google_login_observed",
        "public_https_endpoint_observed",
        "no_fake_google_provider",
        "no_simulated_chatgpt_client",
        "public_discovery_without_oauth_observed",
        "protected_tool_challenge_observed",
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
        "no_sensitive_material_in_packet",
    },
    "reviewer_gate": {
        "read_only_reviewers_used",
        "no_outstanding_blockers",
        "scoped_packet_excluded_sensitive_material",
    },
    "completion_audit": {
        "independent_completion_audit_used",
        "all_layer_artifacts_recomputed",
        "actor_context_contract_reviewed",
        "documentation_state_reviewed",
        "work_board_remains_authoritative",
        "no_sensitive_material_in_packet",
    },
}

_EXTERNAL_PACKET_TYPE = "issue20_oauth_external_closure_evidence"
_EXTERNAL_PACKET_SCHEMA_VERSION = 5
_EXTERNAL_SOURCE_COMMITMENT_FIELDS = (
    ("live_postgresql", "source_report_commitment_hash"),
    ("operator_cli_postgresql", "journey_report_hash"),
    ("production_container_lifecycle", "run_report_set_hash"),
    ("mcp_inspector", "source_evidence_artifact_hash"),
    ("live_chatgpt_google", "source_evidence_artifact_hash"),
    ("reviewer_gate", "source_evidence_artifact_hash"),
    ("completion_audit", "source_evidence_artifact_hash"),
)
_EXTERNAL_REPORT_STATUS_FIELDS = {
    "live_postgresql": "live_postgresql_rollback_status",
    "operator_cli_postgresql": "operator_cli_postgresql_status",
    "production_container_lifecycle": "production_container_lifecycle_status",
    "mcp_inspector": "mcp_inspector_remote_status",
    "live_chatgpt_google": "live_https_chatgpt_google_status",
    "reviewer_gate": "reviewer_gate_status",
    "completion_audit": "completion_audit_status",
}
_EXTERNAL_REPORT_ARTIFACT_FIELDS = {
    "live_postgresql": "live_postgresql_artifact_hash",
    "operator_cli_postgresql": "operator_cli_postgresql_artifact_hash",
    "production_container_lifecycle": "production_container_lifecycle_artifact_hash",
    "mcp_inspector": "mcp_inspector_artifact_hash",
    "live_chatgpt_google": "live_chatgpt_google_artifact_hash",
    "reviewer_gate": "reviewer_gate_artifact_hash",
    "completion_audit": "completion_audit_artifact_hash",
}
_PRODUCTION_CONTAINER_LIFECYCLE_SEQUENCE = (
    "runtime_image_built",
    "fresh_postgresql_started",
    "migrations_applied",
    "real_google_preflight_completed",
    "production_bridge_oauth_seeded",
    "first_container_ready",
    "first_bearer_whoami_upload_and_forgery_denial",
    "first_sigterm_and_state_snapshot",
    "restart_migration_noop",
    "second_container_same_bearer_whoami",
    "second_sigterm_and_stable_core_state",
    "overlap_manifest_reloaded_with_two_public_keys",
    "overlap_sigterm_and_verify_until_elapsed",
    "retired_manifest_reloaded_with_one_public_key",
    "final_sigterm_and_resource_cleanup",
)
_MCP_INSPECTOR_SEQUENCE = (
    "unauthenticated_initialize_public",
    "unauthenticated_tools_list_public",
    "unauthenticated_protected_tool_call_challenged",
    "synthetic_invalid_bearer_protected_tool_call_challenged",
    "inspector_no_semantic_result_or_partial_state_verified",
)
_LIVE_CHATGPT_GOOGLE_SEQUENCE = (
    "chatgpt_connector_discovery_initialize",
    "chatgpt_connector_discovery_tools_list",
    "chatgpt_protected_tool_oauth_challenge",
    "first_owner_google_authorization",
    "first_owner_google_callback",
    "first_owner_formowl_token_exchange",
    "first_owner_whoami",
    "first_owner_open_upload_session",
    "second_real_google_user_invited",
    "second_real_google_user_authorization",
    "second_real_google_user_callback",
    "second_real_google_user_token_exchange",
    "second_real_google_user_whoami",
    "second_real_google_user_member_workspace_shape_verified",
    "second_user_owner_only_action_denied",
    "second_user_cross_workspace_action_denied",
    "mcp_identity_forgery_denied",
    "all_semantic_denials_returned_no_result_or_partial_state",
    "second_user_membership_removed",
    "membership_removal_revoked_one_session",
    "removed_membership_old_token_denied",
    "runtime_restarted_with_membership_removed",
    "removed_membership_old_token_denied_after_restart",
    "removed_membership_relink_denied",
    "removed_membership_relink_zero_partial_state_verified",
    "second_user_membership_restored",
    "same_subject_relinked_with_new_session_after_restore",
    "restored_session_whoami",
    "removed_old_session_still_denied_after_restore",
    "restored_session_revoked",
    "revoked_token_denied",
    "same_subject_relinked_after_revocation",
    "post_revocation_relinked_whoami",
    "relinked_token_expired",
    "expired_token_denied",
    "same_subject_relinked_after_expiry",
    "post_expiry_relinked_whoami",
)
_LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS = (
    "sequence_index",
    "event_name",
    "action",
    "status",
    "reason_code",
    "actor_type",
    "actor_user_binding_hash",
    "actor_service_binding_hash",
    "approval_user_binding_hash",
    "workspace_binding_hash",
    "external_identity_binding_hash",
    "oauth_client_binding_hash",
    "oauth_token_session_binding_hash",
    "request_binding_hash",
    "tool_call_binding_hash",
    "metadata_shape_hash",
    "previous_audit_record_hash",
    "audit_record_hash",
)
_LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE = (
    "owner_bootstrap_created_service",
    "owner_oauth_authorization_started",
    "owner_google_authentication_succeeded",
    "owner_external_identity_created",
    "owner_invitation_accepted",
    "owner_authorization_code_issued",
    "owner_token_session_issued",
    "owner_whoami_allowed",
    "owner_upload_session_allowed",
    "second_user_invitation_created_service",
    "second_user_oauth_authorization_started",
    "second_user_google_authentication_succeeded",
    "second_user_external_identity_created",
    "second_user_invitation_accepted",
    "second_user_authorization_code_issued",
    "second_user_token_session_issued",
    "second_user_whoami_allowed",
    "second_user_owner_only_denied",
    "second_user_cross_workspace_denied",
    "forged_identity_denied",
    "second_user_membership_removed_service",
    "removed_old_token_denied",
    "restart_removed_old_token_denied",
    "removed_relink_oauth_authorization_started",
    "removed_relink_google_callback_denied",
    "second_user_membership_restored_service",
    "restore_relink_oauth_authorization_started",
    "restore_relink_google_authentication_succeeded",
    "restore_relink_external_identity_resolved",
    "restore_relink_authorization_code_issued",
    "restore_relink_token_session_issued",
    "restore_relink_whoami_allowed",
    "restored_session_revoked_service",
    "revoked_token_denied",
    "post_revocation_relink_oauth_authorization_started",
    "post_revocation_relink_google_authentication_succeeded",
    "post_revocation_relink_external_identity_resolved",
    "post_revocation_relink_authorization_code_issued",
    "post_revocation_relink_token_session_issued",
    "post_revocation_relink_whoami_allowed",
    "expired_token_denied",
    "post_expiry_relink_oauth_authorization_started",
    "post_expiry_relink_google_authentication_succeeded",
    "post_expiry_relink_external_identity_resolved",
    "post_expiry_relink_authorization_code_issued",
    "post_expiry_relink_token_session_issued",
    "post_expiry_relink_whoami_allowed",
)
_MCP_INSPECTOR_EXACT_COUNTS = {
    "unauthenticated_initialize_count": 1,
    "unauthenticated_tools_list_count": 1,
    "protected_tool_challenge_count": 1,
    "invalid_bearer_challenge_count": 1,
    "semantic_result_count": 0,
    "partial_state_write_count": 0,
}
_LIVE_CHATGPT_GOOGLE_EXACT_COUNTS = {
    "discovery_initialize_count": 1,
    "discovery_tools_list_count": 1,
    "protected_tool_challenge_count": 1,
    "google_authorization_count": 6,
    "google_callback_count": 6,
    "token_exchange_count": 5,
    "whoami_count": 5,
    "upload_session_count": 1,
    "second_user_invitation_count": 1,
    "second_user_google_login_count": 1,
    "second_user_whoami_count": 1,
    "distinct_external_subject_count": 2,
    "distinct_formowl_user_count": 2,
    "second_user_member_workspace_binding_count": 1,
    "owner_only_denial_count": 1,
    "cross_workspace_denial_count": 1,
    "forgery_denial_count": 1,
    "owner_only_denial_semantic_result_count": 0,
    "owner_only_denial_partial_state_write_count": 0,
    "cross_workspace_denial_semantic_result_count": 0,
    "cross_workspace_denial_partial_state_write_count": 0,
    "forgery_denial_semantic_result_count": 0,
    "forgery_denial_partial_state_write_count": 0,
    "membership_removal_count": 1,
    "membership_removal_service_audit_count": 1,
    "removal_revoked_session_count": 1,
    "removed_token_denial_count": 1,
    "restart_removed_token_denial_count": 1,
    "removed_membership_relink_denial_count": 1,
    "removed_relink_authorization_code_issued_count": 0,
    "removed_relink_token_session_created_count": 0,
    "removed_relink_membership_write_count": 0,
    "membership_restore_count": 1,
    "membership_restore_service_audit_count": 1,
    "owner_attributed_membership_mutation_count": 0,
    "post_restore_old_session_denial_count": 1,
    "restore_relink_same_subject_user_new_session_count": 1,
    "post_revocation_relink_same_subject_user_new_session_count": 1,
    "post_expiry_relink_same_subject_user_new_session_count": 1,
    "revocation_count": 1,
    "revoked_token_denial_count": 1,
    "expiry_denial_count": 1,
    "relink_count": 3,
    "relinked_whoami_count": 3,
    "audit_lineage_event_count": len(_LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE),
}
_ISSUE20_COMPLETION_JOURNEYS = (
    "fresh_database_created",
    "migrations_applied",
    "first_owner_bootstrap_completed",
    "authentication_state_persisted",
    "upload_session_persisted",
    "audit_lineage_persisted",
    "persisted_state_reloaded_after_restart",
    "operator_cli_postgresql_journey_completed",
    "production_container_lifecycle_completed",
    "signing_key_rotation_completed",
    "second_real_google_user_invited_and_linked",
    "mcp_inspector_public_discovery_completed",
    "mcp_inspector_security_metadata_completed",
    "mcp_inspector_protected_tool_challenge_completed",
    "mcp_inspector_invalid_bearer_challenge_completed",
    "mcp_inspector_no_semantic_result_or_partial_state_completed",
    "live_chatgpt_google_public_discovery_completed",
    "live_chatgpt_google_owner_connector_completed",
    "live_chatgpt_google_second_real_user_identity_completed",
    "live_chatgpt_google_second_user_member_workspace_completed",
    "live_chatgpt_google_owner_only_denial_completed",
    "live_chatgpt_google_cross_workspace_denial_completed",
    "live_chatgpt_google_forgery_denial_completed",
    "live_chatgpt_google_denials_no_result_or_partial_state_completed",
    "live_chatgpt_google_membership_removal_restart_denials_completed",
    "live_chatgpt_google_removed_membership_relink_zero_state_completed",
    "live_chatgpt_google_membership_restore_identity_session_completed",
    "live_chatgpt_google_old_session_post_restore_denial_completed",
    "live_chatgpt_google_revocation_denial_relink_completed",
    "live_chatgpt_google_expiry_denial_relink_completed",
    "live_chatgpt_google_audit_lineage_verified",
    "actor_context_contract_verified",
    "documentation_contract_verified",
    "three_reviewer_gate_agreed",
)
_ACTOR_CONTEXT_CONTRACT_PATHS = (
    "python/formowl_auth/provider.py",
    "python/formowl_auth/service.py",
    "python/formowl_gateway/remote.py",
    "python/formowl_contract/models.py",
)
_PRE_CLOSURE_OPERATOR_DEPLOY_DOCUMENTATION_PATHS = (
    "deploy/connected/Caddyfile.example",
    "deploy/connected/compose.env.example",
    "deploy/connected/secrets/README.md",
    "deploy/connected/signing-key-set.example.json",
)
_PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS = (
    "SPEC.md",
    *_PRE_CLOSURE_OPERATOR_DEPLOY_DOCUMENTATION_PATHS,
    "docs/closed-beta-runbook.md",
    "docs/infra-spec.md",
    "docs/mcp-boundaries.md",
    "docs/workflows.md",
    "docs/issue20-oauth-evidence-runbook.md",
)
_DOCUMENTATION_CONTRACT_PATHS = _PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS
_REVIEWER_GATE_GOVERNANCE_PATHS = ("docs/agent-goals/reviewer-gate.md",)
_COMPLETION_STATE_CONTRACT_PATHS = (
    "README.md",
    "docs/implementation-task-breakdown.md",
    "docs/agent-goals/system-backbone-agent.md",
    "docs/agent-goals/handoff-log.md",
    "docs/issue20-account-system-verification-status.md",
)
_ISSUE20_BOARD_OPEN_MARKER = (
    "- [ ] Implement issue #20 Google-backed ChatGPT MCP OAuth identity mapping and"
)
_ISSUE20_BOARD_COMPLETE_MARKER = (
    "- [x] Implement issue #20 Google-backed ChatGPT MCP OAuth identity mapping and"
)
_ISSUE20_BOARD_COMPLETION_REPLACEMENTS = (
    (
        "validator blockers; seven external layers remain `not_supplied`, so #20\n" "  stays open.",
        "validator blockers; all seven external layers are `accepted`, and #20 is\n"
        "  complete via `issue20_post_audit_transition_v1`; this does not establish\n"
        "  production readiness.",
    ),
    (
        "This bounded batch reviewer\n"
        "    gate is not the Issue #20-wide reviewer external layer, which remains\n"
        "    `not_supplied`.",
        "This bounded batch reviewer\n"
        "    gate remains scoped and does not itself establish the separately accepted\n"
        "    Issue #20-wide reviewer external layer.",
    ),
    (
        "  - Remaining state: issue #20 stays unchecked and open. Repository authority is",
        "  - Completion state: issue #20 is complete via\n"
        "    `issue20_post_audit_transition_v1`. Repository authority remains",
    ),
    (
        "  - External state: `live_postgresql`, `operator_cli_postgresql`,\n"
        "    `production_container_lifecycle`, `mcp_inspector`, `live_chatgpt_google`,\n"
        "    `reviewer_gate`, and `completion_audit` remain `not_supplied`.",
        "  - External closure state: `live_postgresql`, `operator_cli_postgresql`,\n"
        "    `production_container_lifecycle`, `mcp_inspector`, `live_chatgpt_google`,\n"
        "    `reviewer_gate`, and `completion_audit` are all `accepted`.",
    ),
    (
        "  - Next: freeze docs/local harness, run all seven external layers, and keep #20 unchecked.",
        "  - Next: archive the accepted Issue #20 closure evidence, continue Issue #41,\n"
        "    and do not expand production-readiness claims.",
    ),
)
_ISSUE20_BOARD_COMPLETE_STATE_MARKERS = (
    "  - Completion state: issue #20 is complete via",
    "  - External closure state: `live_postgresql`, `operator_cli_postgresql`,",
    "  - Next: archive the accepted Issue #20 closure evidence, continue Issue #41,",
)
_ISSUE41_BOARD_OPEN_MARKER = (
    "- [ ] Implement issue #41 generic Core Asset Storage identity binding, tenant"
)
_ISSUE20_README_OPEN_MARKER = (
    "Those external\n"
    "journeys are not yet accepted completion evidence, so issue #20 remains open\n"
    "and no production-readiness claim is made."
)
_ISSUE20_README_TRANSITION_SENTENCE = (
    "The governed Issue #20 external evidence, 3/3 reviewer gate, and independent "
    "completion audit are accepted for closure; this does not establish production "
    "readiness."
)
_ISSUE20_README_COMPLETE_MARKER = (
    "- Issue #20 closure state: `complete` via "
    "`issue20_post_audit_transition_v1`; this does not establish production readiness."
)
_ISSUE20_README_COMPLETE_HEADING = "## Issue #20 Closure Status"
_ISSUE20_GOAL_COMPLETE_MARKERS = (
    "- Issue #20 closure state: `complete` via `issue20_post_audit_transition_v1`;",
    "- Issue #20 next action: archive the accepted closure evidence without",
)
_ISSUE20_GOAL_OPEN_EXTERNAL_STATE = (
    "- All required external layers remain `not_supplied`: `live_postgresql`,\n"
    "  `operator_cli_postgresql`, `production_container_lifecycle`, `mcp_inspector`,\n"
    "  `live_chatgpt_google`, `reviewer_gate`, and `completion_audit`. Issue #20\n"
    "  remains open and no production-readiness claim is supported."
)
_ISSUE20_GOAL_COMPLETE_EXTERNAL_STATE = (
    "- Issue #20 closure state: `complete` via `issue20_post_audit_transition_v1`;\n"
    "  all seven required external layers are `accepted`. This closure does not\n"
    "  establish production readiness."
)
_ISSUE20_GOAL_OPEN_NEXT_ACTION = (
    "Freeze the final docs and local harness authority, then run the governed\n"
    "`live_postgresql`, `operator_cli_postgresql`,\n"
    "`production_container_lifecycle`, `mcp_inspector`, and\n"
    "`live_chatgpt_google` campaigns with the operator-recorded predefined client ID\n"
    "and ChatGPT-displayed callback; stop if app management cannot use that same ID.\n"
    "Prepare the frozen-source Issue-wide\n"
    "`reviewer_gate` packet only after those campaigns, then run the independent\n"
    "`completion_audit`. Keep Issue #20 open until all seven layers agree."
)
_ISSUE20_GOAL_COMPLETE_NEXT_ACTION = (
    "- Issue #20 next action: archive the accepted closure evidence without\n"
    "  expanding production-readiness claims.\n"
    "- Preserve the operator-recorded predefined client ID and ChatGPT-displayed\n"
    "  callback as the accepted campaign authority; do not claim ChatGPT generated\n"
    "  or displayed the client ID, and do not substitute another registration model.\n"
    "- Continue the System Backbone objective with Issue #41's generic Asset\n"
    "  tenant, owner, lifecycle, retention, purge, and authorization boundary."
)
_ISSUE20_HANDOFF_COMPLETE_HEADING = "## 2026-07-20 — Issue #20 governed post-audit closure"
_ISSUE20_HANDOFF_COMPLETE_MARKER = (
    "- Issue #20 final closure: `complete` via "
    "`issue20_post_audit_transition_v1`; Issue #41 remains unchanged and no "
    "production-readiness claim is added."
)
_ISSUE20_VERIFICATION_PRE_CLOSURE_HEADING = "## Preserved Pre-Closure Verification Record"
_ISSUE20_VERIFICATION_COMPLETE_HEADING = "## Governed Post-Audit Closure"
_ISSUE20_VERIFICATION_COMPLETE_MARKERS = (
    "- 狀態：Issue #20 已完成 governed post-audit transition，可關閉；"
    "不構成 production-ready 宣稱",
    "- 七個 required external layers：全部 `accepted`",
    "- Reviewer gate：3/3 `AGREE`",
    "- Independent completion audit：`passed`",
    "- Product-level production readiness：未宣稱",
    "- RELEASE_DECISION: CLOSE",
)
_ISSUE20_GOAL_OPEN_MARKERS = (
    "- Label: `active-blocked`",
    "`blocked`",
    "Keep Issue #20 open until all seven layers agree.",
)
_ISSUE20_VERIFICATION_OPEN_MARKER = (
    "- 狀態：Issue #20 仍為 open，不可宣稱完成、可關閉或 production ready"
)
_ISSUE20_COMPLETION_MARKERS_BY_PATH = {
    "README.md": (
        _ISSUE20_README_COMPLETE_HEADING,
        _ISSUE20_README_COMPLETE_MARKER,
    ),
    "docs/agent-goals/system-backbone-agent.md": _ISSUE20_GOAL_COMPLETE_MARKERS,
    "docs/agent-goals/handoff-log.md": (
        _ISSUE20_HANDOFF_COMPLETE_HEADING,
        _ISSUE20_HANDOFF_COMPLETE_MARKER,
    ),
    "docs/issue20-account-system-verification-status.md": (_ISSUE20_VERIFICATION_COMPLETE_MARKERS),
}
_PRE_CLOSURE_MANIFEST_TYPE = "issue20_preclosure_manifest"
_PRE_CLOSURE_MANIFEST_SCHEMA_VERSION = 1
_PRE_CLOSURE_MANIFEST_FIELDS = {
    "artifact_type",
    "schema_version",
    "status",
    "operator_attested",
    "closure_transition_plan_hash",
    "reviewer_gate_governance_hash",
    "external_evidence_packet_hash",
    "preclosure_documentation_contract_hash",
    "reviewer_gate_artifact_hash",
    "completion_audit_artifact_hash",
    "mutable_document_before_hashes",
    "mutable_document_expected_after_hashes",
    "non_issue20_checkbox_manifest_hash",
    "issue41_checkbox_hash",
    "production_ready_assertion_manifest_hash",
    "evidence_artifact_hash",
    "attestations",
}
_PRE_CLOSURE_MANIFEST_ATTESTATIONS = {
    "all_external_layers_accepted",
    "reviewer_gate_three_of_three_agree",
    "independent_completion_audit_passed",
    "issue20_board_was_open",
    "completion_markers_were_absent",
    "no_sensitive_material_in_artifact",
}
_COMPLETION_TRANSITION_TYPE = "issue20_post_audit_transition_v1"
_COMPLETION_TRANSITION_SCHEMA_VERSION = 1
_COMPLETION_TRANSITION_FIELDS = {
    "artifact_type",
    "schema_version",
    "status",
    "operator_attested",
    "preclosure_manifest_hash",
    "closure_transition_plan_hash",
    "reviewer_gate_governance_hash",
    "external_evidence_packet_hash",
    "preclosure_documentation_contract_hash",
    "completion_state_before_hashes_hash",
    "completion_state_after_hashes_hash",
    "mutable_document_after_hashes",
    "non_issue20_checkbox_manifest_hash",
    "issue41_checkbox_hash",
    "production_ready_assertion_manifest_hash",
    "reviewer_gate_artifact_hash",
    "completion_audit_artifact_hash",
    "evidence_artifact_hash",
    "attestations",
}
_COMPLETION_TRANSITION_ATTESTATIONS = {
    "all_external_layers_accepted",
    "reviewer_gate_three_of_three_agree",
    "independent_completion_audit_passed",
    "completion_state_updated_after_audit",
    "substantive_documentation_unchanged",
    "only_issue20_checkbox_transitioned",
    "issue41_remained_open",
    "production_ready_claim_not_expanded",
    "no_sensitive_material_in_artifact",
}
_CLOSURE_TRANSITION_PLAN = {
    "plan_type": "issue20_completion_transition_plan_v1",
    "preclosure_documentation_paths": _PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
    "reviewer_gate_governance_paths": _REVIEWER_GATE_GOVERNANCE_PATHS,
    "mutable_completion_state_paths": _COMPLETION_STATE_CONTRACT_PATHS,
    "board_transition": {
        "before": _ISSUE20_BOARD_OPEN_MARKER,
        "after": _ISSUE20_BOARD_COMPLETE_MARKER,
        "unchanged_issue41": _ISSUE41_BOARD_OPEN_MARKER,
    },
    "readme_transition": {
        "before": _ISSUE20_README_OPEN_MARKER,
        "after": _ISSUE20_README_TRANSITION_SENTENCE,
    },
    "required_completion_markers_by_path": _ISSUE20_COMPLETION_MARKERS_BY_PATH,
    "completion_document_transform": "issue20_completion_document_transform_v1",
    "production_ready_claim_must_not_expand": True,
}
_CLOSURE_TRANSITION_PLAN_HASH = sha256_json(_CLOSURE_TRANSITION_PLAN)
_LOCAL_COMPLETION_SAFE_OUTPUT_FIELDS = (
    "implementation_contract_hash",
    "manifest_hash",
    "changed_function_set_hash",
    "scenario_contract_hash",
    "http_exchange_shape_hash",
    "audit_lineage_shape_hash",
    "negotiated_protocol_version_hash",
    "supported_protocol_matrix_hash",
    "manifest_test_set_hash",
    "executed_test_set_hash",
    "function_coverage_pairs_hash",
    "function_entry_count",
    "onboarded_function_count",
    "pending_function_count",
    "changed_function_count",
    "test_id_count",
    "manifest_requested_test_count",
    "manifest_resolved_test_count",
    "manifest_run_count",
    "manifest_pass_count",
    "manifest_skip_count",
    "manifest_failure_count",
    "manifest_error_count",
    "manifest_expected_failure_count",
    "manifest_unexpected_success_count",
    "manifest_resolution_blocker_count",
    "manifest_covered_function_count",
    "manifest_checked_pair_count",
    "manifest_execution_blocker_count",
    "http_exchange_count",
    "negative_case_count",
    "rollback_case_count",
    "audit_event_count",
)
_MISSING_HASH = sha256_json({"missing": True})

REQUIRED_METRICS = (
    "metadata_and_jwks_verified",
    "protocol_negotiation_verified",
    "unauthenticated_challenges_verified",
    "authorization_code_pkce_flow_verified",
    "google_identity_mapping_verified",
    "bearer_streamable_http_mcp_verified",
    "whoami_verified",
    "allowed_workspace_upload_session_verified",
    "cross_workspace_and_forgery_denied",
    "revocation_immediate",
    "same_subject_reconnect_verified",
    "negative_matrix_verified",
    "rollback_matrix_verified",
    "audit_lineage_verified",
    "leak_scan_verified",
    "function_manifest_verified",
    "function_test_execution_verified",
    "function_onboarding_verified",
    "deterministic_fake_e2e_passed",
)


class _LocalCompletionContext:
    __slots__ = (
        "implementation_base_hash",
        "metrics",
        "safe_outputs",
        "local_completion_audit_report_hash",
    )

    def __init__(
        self,
        *,
        implementation_base_hash: str,
        metrics: dict[str, bool],
        safe_outputs: dict[str, Any],
        local_completion_audit_report_hash: str,
    ) -> None:
        self.implementation_base_hash = implementation_base_hash
        self.metrics = metrics
        self.safe_outputs = safe_outputs
        self.local_completion_audit_report_hash = local_completion_audit_report_hash


class LifecycleEvidenceError(RuntimeError):
    """Bounded lifecycle aggregation failure safe for public CLI output."""

    def __init__(self, code: str) -> None:
        self.code = (
            code if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) else ("lifecycle_evidence_invalid")
        )
        super().__init__(self.code)


class OperatorEvidenceError(RuntimeError):
    """Bounded operator-journey conversion failure safe for public CLI output."""

    def __init__(self, code: str) -> None:
        self.code = (
            code if re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) else "operator_evidence_invalid"
        )
        super().__init__(self.code)


def aggregate_production_container_lifecycle_reports(
    reports: Sequence[Mapping[str, Any]],
    *,
    operator_attested: bool,
) -> dict[str, Any]:
    """Convert distinct validated lifecycle reports into one external layer."""

    if operator_attested is not True:
        raise LifecycleEvidenceError("lifecycle_operator_attestation_missing")
    if len(reports) < 2:
        raise LifecycleEvidenceError("lifecycle_two_fresh_runs_required")
    validated_runs: list[tuple[str, dict[str, Any]]] = []
    for raw_report in reports:
        if not isinstance(raw_report, Mapping):
            raise LifecycleEvidenceError("lifecycle_report_invalid")
        report = dict(raw_report)
        validation = _lifecycle_probe.validate_report(report)
        if validation.get("passed") is not True or report.get("status") != "passed":
            raise LifecycleEvidenceError("lifecycle_report_invalid")
        validated_runs.append((sha256_json(report), report))
    if len({report_hash for report_hash, _ in validated_runs}) != len(validated_runs):
        raise LifecycleEvidenceError("lifecycle_duplicate_report_rejected")
    validated_runs.sort(key=lambda item: item[0])
    if any(
        len({report["safe_hashes"][field] for _, report in validated_runs}) != 1
        for field in _LIFECYCLE_STABLE_HASH_FIELDS
    ):
        raise LifecycleEvidenceError("lifecycle_static_fingerprint_mismatch")
    report_hashes = [report_hash for report_hash, _ in validated_runs]
    run_report_set_hash = sha256_json(
        {
            "binding_type": "production_container_lifecycle_run_report_set_v1",
            "report_hashes": report_hashes,
        }
    )
    aggregate_hashes = {
        field: sha256_json(
            {
                "binding_type": "production_container_lifecycle_field_aggregate_v2",
                "field": field,
                "run_bindings": [
                    {
                        "report_hash": report_hash,
                        "value_hash": report["safe_hashes"][field],
                    }
                    for report_hash, report in validated_runs
                ],
            }
        )
        for field in _LIFECYCLE_EXTERNAL_HASH_FIELDS
    }
    layer = {
        "status": "passed",
        "operator_attested": True,
        "endpoint_scheme": "container",
        "implementation_contract_hash": validated_runs[0][1]["safe_hashes"][
            "implementation_contract_hash"
        ],
        "sequence_hash": sha256_json(_PRODUCTION_CONTAINER_LIFECYCLE_SEQUENCE),
        "run_report_set_hash": run_report_set_hash,
        **aggregate_hashes,
        "run_count": len(validated_runs),
        "pass_count": len(validated_runs),
        "failure_count": 0,
        "skip_count": 0,
        "compose_runtime_process_uid": validated_runs[0][1]["safe_counts"][
            "compose_runtime_process_uid"
        ],
        "runtime_process_uid": validated_runs[0][1]["safe_counts"]["runtime_process_uid"],
        **{
            external_field: sum(report["safe_counts"][source_field] for _, report in validated_runs)
            for external_field, source_field in _LIFECYCLE_EXTERNAL_COUNT_SOURCES.items()
        },
        "stateful_restart_count": len(validated_runs),
        "attestations": {
            "actual_runtime_image_used": True,
            "actual_entrypoint_used": True,
            "actual_compose_stack_used": True,
            "file_mounted_secrets_used": True,
            "operator_owned_0400_secret_sources_observed": True,
            "compose_migrate_and_preflight_observed": True,
            "compose_secret_snapshots_and_retirement_observed": True,
            "runtime_uid_10001_observed": True,
            "jwks_one_two_one_observed": True,
            "real_google_preflight_observed": True,
            "sigterm_graceful_exit_observed": True,
            "stateful_restart_observed": True,
            "no_sensitive_material_in_packet": True,
        },
    }
    layer["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": _LIFECYCLE_EXTERNAL_LAYER_BINDING_TYPE,
            "layer_without_artifact_hash": layer,
        }
    )
    validation = validate_production_container_lifecycle_external_layer(layer)
    if validation["passed"] is not True:
        raise LifecycleEvidenceError("lifecycle_external_layer_invalid")
    return layer


def validate_production_container_lifecycle_external_layer(layer: Any) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blocker_count": 1,
        }
    value = dict(layer)
    _exact_keys(
        value,
        set(_EXTERNAL_LAYER_FIELDS["production_container_lifecycle"]),
        "production_container_lifecycle",
        blockers,
    )
    if value.get("status") != "passed":
        blockers.append("production container lifecycle evidence did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("production container lifecycle operator attestation is missing")
    _validate_external_hash_fields("production_container_lifecycle", value, blockers)
    _validate_external_attestations(
        "production_container_lifecycle",
        value.get("attestations"),
        blockers,
    )
    _validate_external_layer_counts("production_container_lifecycle", value, blockers)
    if value.get("implementation_contract_hash") != issue20_implementation_contract_hash(ROOT):
        blockers.append("production container lifecycle implementation contract is stale")
    artifact_source = {key: item for key, item in value.items() if key != "evidence_artifact_hash"}
    expected_artifact_hash = sha256_json(
        {
            "binding_type": _LIFECYCLE_EXTERNAL_LAYER_BINDING_TYPE,
            "layer_without_artifact_hash": artifact_source,
        }
    )
    if value.get("evidence_artifact_hash") != expected_artifact_hash:
        blockers.append("production container lifecycle artifact binding mismatch")
    if value.get("compose_runtime_process_uid") != _lifecycle_probe.RUNTIME_UID:
        blockers.append("production container lifecycle Compose runtime UID mismatch")
    if value.get("runtime_process_uid") != _lifecycle_probe.RUNTIME_UID:
        blockers.append("production container lifecycle runtime UID mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("production container lifecycle evidence contains sensitive material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def build_operator_cli_postgresql_external_layer(
    report: Mapping[str, Any],
    *,
    operator_attested: bool,
    trusted_execution_authority: Mapping[str, Any] | None,
    trusted_execution_authority_pin: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Convert one current production operator journey report into its external layer."""

    if operator_attested is not True:
        raise OperatorEvidenceError("operator_evidence_attestation_missing")
    if not isinstance(report, Mapping):
        raise OperatorEvidenceError("operator_evidence_report_invalid")
    report_value = dict(report)
    if "schema_version" not in report_value:
        raise OperatorEvidenceError("operator_evidence_report_invalid")
    if report_value.get("schema_version") != _OPERATOR_SOURCE_SCHEMA_VERSION:
        raise OperatorEvidenceError("operator_evidence_schema_v2_required")
    if not isinstance(trusted_execution_authority, Mapping):
        raise OperatorEvidenceError("operator_execution_authority_required")
    if not isinstance(trusted_execution_authority_pin, Mapping):
        raise OperatorEvidenceError("operator_execution_authority_pin_required")
    execution_authority = dict(trusted_execution_authority)
    execution_authority_pin = dict(trusted_execution_authority_pin)
    report_validation = _operator_journey.validate_report(
        report_value,
        trusted_execution_authority=execution_authority,
        trusted_execution_authority_pin=execution_authority_pin,
    )
    if report_validation.get("passed") is not True:
        raise OperatorEvidenceError("operator_evidence_report_invalid")
    counts = report_value.get("counts")
    output_hashes = report_value.get("operator_output_hashes")
    if not isinstance(counts, Mapping) or not isinstance(output_hashes, Mapping):
        raise OperatorEvidenceError("operator_evidence_report_invalid")
    execution_receipt = report_value.get("execution_receipt")
    if not isinstance(execution_receipt, Mapping):
        raise OperatorEvidenceError("operator_evidence_report_invalid")
    if (
        dict(counts) != _OPERATOR_V2_SOURCE_EXACT_COUNTS
        or set(output_hashes) != _OPERATOR_V2_OUTPUT_LABELS
        or set(report_value.get("attestations", {})) != _OPERATOR_V2_SOURCE_ATTESTATIONS
        or any(value is not True for value in report_value.get("attestations", {}).values())
    ):
        raise OperatorEvidenceError("operator_evidence_report_invalid")
    layer = {
        "status": "passed",
        "operator_attested": True,
        "endpoint_scheme": "container_postgresql",
        "source_schema_version": _OPERATOR_SOURCE_SCHEMA_VERSION,
        "implementation_contract_hash": report_value["implementation_contract_hash"],
        "runtime_image_id_hash": report_value["runtime_image_id_hash"],
        "postgres_image_digest_hash": _OPERATOR_POSTGRES_IMAGE_DIGEST_HASH,
        "operator_authority_contract_hash": _OPERATOR_V2_AUTHORITY_CONTRACT_HASH,
        "journey_script_hash": report_value["journey_script_hash"],
        "journey_report_hash": sha256_json(report_value),
        "execution_authority_hash": execution_receipt["execution_authority_hash"],
        "execution_authority_pin_hash": execution_receipt["execution_authority_pin_hash"],
        "campaign_nonce_hash": execution_receipt["campaign_nonce_hash"],
        "receipt_public_key_hex": execution_authority["receipt_public_key_hex"],
        "receipt_public_key_hash": execution_authority["receipt_public_key_hash"],
        "unsigned_report_hash": execution_receipt["unsigned_report_hash"],
        "execution_receipt_payload_hash": execution_receipt["signed_payload_hash"],
        "execution_receipt_signature_hex": execution_receipt["signature_hex"],
        "secret_initialization_contract_hash": report_value["secret_initialization_contract_hash"],
        "migration_result_hash": report_value["migration_result_hash"],
        "operator_output_set_hash": sha256_json(dict(sorted(output_hashes.items()))),
        "operator_audit_contract_hash": output_hashes["operator-audit-contract"],
        "operator_rollback_state_hash": output_hashes["operator-rollback-state"],
        "operator_denial_hash": report_value["operator_denial_hash"],
        "run_count": 1,
        "pass_count": 1,
        "failure_count": 0,
        "skip_count": 0,
        **{
            layer_field: counts[source_field]
            for layer_field, source_field in _OPERATOR_LAYER_COUNT_SOURCES.items()
        },
        "attestations": {
            "actual_runtime_image_used": True,
            "clean_secret_bootstrap_used": True,
            "fresh_postgresql_used": True,
            "installed_runtime_package_used": True,
            "operator_cli_allow_and_deny_observed": True,
            "operator_audits_persisted": True,
            "exact_operator_lifecycle_observed": True,
            "member_approval_denial_audited": True,
            "membership_rollback_verified": True,
            "immutable_runtime_and_postgres_images_used": True,
            "no_sensitive_material_in_packet": True,
        },
    }
    layer["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": _OPERATOR_EXTERNAL_LAYER_BINDING_TYPE,
            "layer_without_artifact_hash": layer,
        }
    )
    validation = validate_operator_cli_postgresql_external_layer(
        layer,
        trusted_execution_authority_pin=execution_authority_pin,
    )
    if validation["passed"] is not True:
        raise OperatorEvidenceError("operator_evidence_layer_invalid")
    return layer


def validate_operator_cli_postgresql_external_layer(
    layer: Any,
    *,
    trusted_execution_authority_pin: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blocker_count": 1,
        }
    value = dict(layer)
    _exact_keys(
        value,
        set(_EXTERNAL_LAYER_FIELDS["operator_cli_postgresql"]),
        "operator_cli_postgresql",
        blockers,
    )
    if value.get("status") != "passed":
        blockers.append("operator CLI PostgreSQL evidence did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("operator CLI PostgreSQL attestation is missing")
    if value.get("source_schema_version") != _OPERATOR_SOURCE_SCHEMA_VERSION:
        blockers.append("operator CLI PostgreSQL source schema v2 is required")
    _validate_external_hash_fields("operator_cli_postgresql", value, blockers)
    _validate_external_attestations(
        "operator_cli_postgresql",
        value.get("attestations"),
        blockers,
    )
    _validate_external_layer_counts("operator_cli_postgresql", value, blockers)
    if value.get("implementation_contract_hash") != issue20_implementation_contract_hash(ROOT):
        blockers.append("operator CLI PostgreSQL implementation contract is stale")
    current_script_hash = _operator_journey._sha256_bytes(
        Path(_operator_journey.__file__).read_bytes()
    )
    if value.get("journey_script_hash") != current_script_hash:
        blockers.append("operator CLI PostgreSQL journey script is stale")
    if value.get("postgres_image_digest_hash") != _OPERATOR_POSTGRES_IMAGE_DIGEST_HASH:
        blockers.append("operator CLI PostgreSQL pinned image digest binding is stale")
    if value.get("operator_authority_contract_hash") != _OPERATOR_V2_AUTHORITY_CONTRACT_HASH:
        blockers.append("operator CLI PostgreSQL v2 authority contract is stale")
    public_key_hex = value.get("receipt_public_key_hex")
    signature_hex = value.get("execution_receipt_signature_hex")
    if not isinstance(public_key_hex, str) or re.fullmatch(r"[0-9a-f]{64}", public_key_hex) is None:
        blockers.append("operator CLI PostgreSQL receipt public key is invalid")
    if not isinstance(signature_hex, str) or re.fullmatch(r"[0-9a-f]{128}", signature_hex) is None:
        blockers.append("operator CLI PostgreSQL receipt signature is invalid")
    execution_authority = {
        "artifact_id": _operator_journey.EXECUTION_AUTHORITY_ARTIFACT_ID,
        "schema_version": 1,
        "campaign_nonce_hash": value.get("campaign_nonce_hash"),
        "receipt_public_key_hex": public_key_hex,
        "receipt_public_key_hash": value.get("receipt_public_key_hash"),
        "implementation_contract_hash": value.get("implementation_contract_hash"),
        "runtime_image_id_hash": value.get("runtime_image_id_hash"),
        "journey_script_hash": value.get("journey_script_hash"),
        "postgres_image_digest_hash": value.get("postgres_image_digest_hash"),
    }
    if value.get("execution_authority_hash") != sha256_json(execution_authority):
        blockers.append("operator CLI PostgreSQL execution authority binding mismatch")
    if not isinstance(trusted_execution_authority_pin, Mapping):
        blockers.append("operator CLI PostgreSQL trusted execution authority pin is required")
        execution_authority_pin: dict[str, Any] = {}
    else:
        execution_authority_pin = dict(trusted_execution_authority_pin)
        pin_validation = _operator_journey.validate_execution_authority_pin(
            execution_authority,
            execution_authority_pin,
        )
        if pin_validation["passed"] is not True:
            blockers.append("operator CLI PostgreSQL execution authority pin mismatch")
        if value.get("execution_authority_pin_hash") != sha256_json(execution_authority_pin):
            blockers.append("operator CLI PostgreSQL execution authority pin binding mismatch")
    receipt_payload = {
        "binding_type": _operator_journey.EXECUTION_RECEIPT_BINDING_TYPE,
        "execution_authority_hash": value.get("execution_authority_hash"),
        "execution_authority_pin_hash": value.get("execution_authority_pin_hash"),
        "campaign_nonce_hash": value.get("campaign_nonce_hash"),
        "unsigned_report_hash": value.get("unsigned_report_hash"),
        "implementation_contract_hash": value.get("implementation_contract_hash"),
        "runtime_image_id_hash": value.get("runtime_image_id_hash"),
        "journey_script_hash": value.get("journey_script_hash"),
        "postgres_image_digest_hash": value.get("postgres_image_digest_hash"),
        "operator_output_set_hash": value.get("operator_output_set_hash"),
        "operator_audit_contract_hash": value.get("operator_audit_contract_hash"),
        "operator_rollback_state_hash": value.get("operator_rollback_state_hash"),
    }
    payload_bytes = json.dumps(
        receipt_payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if value.get("execution_receipt_payload_hash") != sha256_json(receipt_payload):
        blockers.append("operator CLI PostgreSQL execution receipt payload mismatch")
    if (
        isinstance(public_key_hex, str)
        and re.fullmatch(r"[0-9a-f]{64}", public_key_hex)
        and isinstance(signature_hex, str)
        and re.fullmatch(r"[0-9a-f]{128}", signature_hex)
    ):
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex)).verify(
                bytes.fromhex(signature_hex),
                payload_bytes,
            )
        except (InvalidSignature, ValueError):
            blockers.append("operator CLI PostgreSQL execution receipt verification failed")
    artifact_source = {key: item for key, item in value.items() if key != "evidence_artifact_hash"}
    expected_artifact_hash = sha256_json(
        {
            "binding_type": _OPERATOR_EXTERNAL_LAYER_BINDING_TYPE,
            "layer_without_artifact_hash": artifact_source,
        }
    )
    if value.get("evidence_artifact_hash") != expected_artifact_hash:
        blockers.append("operator CLI PostgreSQL artifact binding mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("operator CLI PostgreSQL evidence contains sensitive material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def build_completion_audit_external_layer(layer: Mapping[str, Any]) -> dict[str, Any]:
    """Add the reproducible public self-binding to completion-audit evidence."""

    value = dict(layer)
    value.pop("evidence_artifact_hash", None)
    expected_fields = set(_EXTERNAL_LAYER_FIELDS["completion_audit"]) - {"evidence_artifact_hash"}
    if set(value) != expected_fields:
        return {}
    value["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": "issue20_completion_audit_external_layer_v1",
            "layer_without_artifact_hash": value,
        }
    )
    return value


def validate_completion_audit_external_layer(layer: Any) -> dict[str, Any]:
    """Validate the completion audit's public self-binding."""

    blockers: list[str] = []
    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blocker_count": 1,
        }
    value = dict(layer)
    _exact_keys(
        value,
        set(_EXTERNAL_LAYER_FIELDS["completion_audit"]),
        "completion_audit",
        blockers,
    )
    if value.get("status") != "passed":
        blockers.append("completion audit evidence did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("completion audit operator attestation is missing")
    _validate_external_hash_fields("completion_audit", value, blockers)
    _validate_external_attestations(
        "completion_audit",
        value.get("attestations"),
        blockers,
    )
    _validate_external_layer_counts("completion_audit", value, blockers)
    expected_layer = build_completion_audit_external_layer(value)
    if not expected_layer or value.get("evidence_artifact_hash") != expected_layer.get(
        "evidence_artifact_hash"
    ):
        blockers.append("completion audit artifact binding mismatch")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def build_mcp_inspector_external_layer(layer: Mapping[str, Any]) -> dict[str, Any]:
    """Add the reproducible public self-binding to an Inspector evidence layer."""

    value = dict(layer)
    value.pop("evidence_artifact_hash", None)
    expected_fields = set(_EXTERNAL_LAYER_FIELDS["mcp_inspector"]) - {"evidence_artifact_hash"}
    if set(value) != expected_fields:
        return {}
    value["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": "issue20_mcp_inspector_external_layer_v1",
            "layer_without_artifact_hash": value,
        }
    )
    return value


def validate_mcp_inspector_external_layer(layer: Any) -> dict[str, Any]:
    """Validate the Inspector source commitment and public self-binding."""

    blockers: list[str] = []
    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blocker_count": 1,
        }
    value = dict(layer)
    _exact_keys(
        value,
        set(_EXTERNAL_LAYER_FIELDS["mcp_inspector"]),
        "mcp_inspector",
        blockers,
    )
    if value.get("status") != "passed":
        blockers.append("MCP Inspector evidence did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("MCP Inspector operator attestation is missing")
    source_hash = value.get("source_evidence_artifact_hash")
    if not _is_sha256(source_hash) or source_hash == _MISSING_HASH:
        blockers.append("MCP Inspector source evidence artifact hash is invalid")
    _validate_external_hash_fields("mcp_inspector", value, blockers)
    _validate_external_attestations(
        "mcp_inspector",
        value.get("attestations"),
        blockers,
    )
    _validate_external_layer_counts("mcp_inspector", value, blockers)
    expected_layer = build_mcp_inspector_external_layer(value)
    if not expected_layer or value.get("evidence_artifact_hash") != expected_layer.get(
        "evidence_artifact_hash"
    ):
        blockers.append("MCP Inspector artifact binding mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("MCP Inspector evidence contains sensitive material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def build_live_chatgpt_google_external_layer(layer: Mapping[str, Any]) -> dict[str, Any]:
    """Add the reproducible public self-binding to live ChatGPT/Google evidence."""

    value = dict(layer)
    value.pop("evidence_artifact_hash", None)
    expected_fields = set(_EXTERNAL_LAYER_FIELDS["live_chatgpt_google"]) - {
        "evidence_artifact_hash"
    }
    if set(value) != expected_fields:
        return {}
    value["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": "issue20_live_chatgpt_google_external_layer_v1",
            "layer_without_artifact_hash": value,
        }
    )
    return value


def validate_live_chatgpt_google_external_layer(layer: Any) -> dict[str, Any]:
    """Validate live ChatGPT/Google source evidence and public self-binding."""

    blockers: list[str] = []
    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blocker_count": 1,
        }
    value = dict(layer)
    _exact_keys(
        value,
        set(_EXTERNAL_LAYER_FIELDS["live_chatgpt_google"]),
        "live_chatgpt_google",
        blockers,
    )
    if value.get("status") != "passed":
        blockers.append("live ChatGPT/Google evidence did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("live ChatGPT/Google operator attestation is missing")
    source_hash = value.get("source_evidence_artifact_hash")
    if not _is_sha256(source_hash) or source_hash == _MISSING_HASH:
        blockers.append("live ChatGPT/Google source evidence artifact hash is invalid")
    _validate_external_hash_fields("live_chatgpt_google", value, blockers)
    _validate_external_attestations(
        "live_chatgpt_google",
        value.get("attestations"),
        blockers,
    )
    _validate_external_layer_counts("live_chatgpt_google", value, blockers)
    expected_layer = build_live_chatgpt_google_external_layer(value)
    if not expected_layer or value.get("evidence_artifact_hash") != expected_layer.get(
        "evidence_artifact_hash"
    ):
        blockers.append("live ChatGPT/Google artifact binding mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("live ChatGPT/Google evidence contains sensitive material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def build_reviewer_gate_external_layer(layer: Mapping[str, Any]) -> dict[str, Any]:
    """Add the reproducible public self-binding to reviewer-gate evidence."""

    value = dict(layer)
    value.pop("evidence_artifact_hash", None)
    expected_fields = set(_EXTERNAL_LAYER_FIELDS["reviewer_gate"]) - {"evidence_artifact_hash"}
    if set(value) != expected_fields:
        return {}
    value["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": "issue20_reviewer_gate_external_layer_v1",
            "layer_without_artifact_hash": value,
        }
    )
    return value


def validate_reviewer_gate_external_layer(layer: Any) -> dict[str, Any]:
    """Validate governed reviewer evidence and its public self-binding."""

    blockers: list[str] = []
    if not isinstance(layer, Mapping):
        return {
            "passed": False,
            "status": "failed",
            "blocker_count": 1,
        }
    value = dict(layer)
    _exact_keys(
        value,
        set(_EXTERNAL_LAYER_FIELDS["reviewer_gate"]),
        "reviewer_gate",
        blockers,
    )
    if value.get("status") != "passed":
        blockers.append("reviewer-gate evidence did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("reviewer-gate operator attestation is missing")
    source_hash = value.get("source_evidence_artifact_hash")
    if not _is_sha256(source_hash) or source_hash == _MISSING_HASH:
        blockers.append("reviewer-gate source evidence artifact hash is invalid")
    _validate_external_hash_fields("reviewer_gate", value, blockers)
    _validate_external_attestations(
        "reviewer_gate",
        value.get("attestations"),
        blockers,
    )
    _validate_external_layer_counts("reviewer_gate", value, blockers)
    expected_layer = build_reviewer_gate_external_layer(value)
    if not expected_layer or value.get("evidence_artifact_hash") != expected_layer.get(
        "evidence_artifact_hash"
    ):
        blockers.append("reviewer-gate artifact binding mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("reviewer-gate evidence contains sensitive material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def _run_local_completion_context(
    *,
    runner: Callable[[], Mapping[str, Any]] = run_issue20_deterministic_e2e,
    manifest_suite_runner: Callable[[Mapping[str, Any]], Mapping[str, Any]] = (
        run_function_harness_test_suite
    ),
) -> _LocalCompletionContext:
    evidence = dict(runner())
    manifest = load_function_harness_manifest()
    onboarding = validate_function_harness_manifest(manifest)
    execution = dict(manifest_suite_runner(manifest))
    execution_validation = validate_function_harness_execution(manifest, execution)
    metrics = {
        key: evidence.get(key) is True
        for key in REQUIRED_METRICS
        if key
        not in {
            "function_manifest_verified",
            "function_test_execution_verified",
            "function_onboarding_verified",
            "deterministic_fake_e2e_passed",
        }
    }
    metrics["function_manifest_verified"] = onboarding["passed"] is True
    metrics["function_test_execution_verified"] = (
        execution.get("passed") is True and execution_validation["passed"] is True
    )
    metrics["function_onboarding_verified"] = (
        metrics["function_manifest_verified"] and metrics["function_test_execution_verified"]
    )
    metrics["deterministic_fake_e2e_passed"] = all(metrics.values())
    local_safe_outputs = _build_local_safe_outputs(
        evidence=evidence,
        onboarding=onboarding,
        execution=execution,
        execution_validation=execution_validation,
    )
    local_completion_audit_report_hash = _local_completion_audit_report_hash(
        implementation_base_hash=sha256_json(ISSUE20_BASE_COMMIT),
        metrics=metrics,
        safe_outputs=local_safe_outputs,
    )
    return _LocalCompletionContext(
        implementation_base_hash=sha256_json(ISSUE20_BASE_COMMIT),
        metrics=metrics,
        safe_outputs=local_safe_outputs,
        local_completion_audit_report_hash=local_completion_audit_report_hash,
    )


def run_oauth_mcp_harness(
    *,
    runner: Callable[[], Mapping[str, Any]] = run_issue20_deterministic_e2e,
    manifest_suite_runner: Callable[[Mapping[str, Any]], Mapping[str, Any]] = (
        run_function_harness_test_suite
    ),
    external_evidence: Mapping[str, Any] | None = None,
    operator_execution_authority_pin: Mapping[str, Any] | None = None,
    production_container_lifecycle_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    local_context = _run_local_completion_context(
        runner=runner,
        manifest_suite_runner=manifest_suite_runner,
    )
    metrics = local_context.metrics
    local_safe_outputs = local_context.safe_outputs
    local_completion_audit_report_hash = local_context.local_completion_audit_report_hash
    if external_evidence is not None and production_container_lifecycle_evidence is not None:
        layer_names = tuple(_EXTERNAL_LAYER_FIELDS)
        external_validation = {
            "passed": False,
            "blockers": ["external evidence inputs are mutually exclusive"],
            "blocker_count": 1,
            "packet_hash": _MISSING_HASH,
            "layer_statuses": {name: "failed" for name in layer_names},
            "layer_artifact_hashes": {name: _MISSING_HASH for name in layer_names},
        }
    elif production_container_lifecycle_evidence is not None:
        layer_names = tuple(_EXTERNAL_LAYER_FIELDS)
        layer_validation = validate_production_container_lifecycle_external_layer(
            production_container_lifecycle_evidence
        )
        layer_statuses = {name: "not_supplied" for name in layer_names}
        layer_statuses["production_container_lifecycle"] = layer_validation["status"]
        layer_artifact_hashes = {name: _MISSING_HASH for name in layer_names}
        if layer_validation["passed"]:
            layer_artifact_hashes["production_container_lifecycle"] = str(
                production_container_lifecycle_evidence["evidence_artifact_hash"]
            )
        blockers = [
            f"external evidence layer was not supplied: {name}"
            for name in layer_names
            if name != "production_container_lifecycle"
        ]
        blockers.extend(
            ["production container lifecycle evidence layer is invalid"]
            * layer_validation["blocker_count"]
        )
        external_validation = {
            "passed": False,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "packet_hash": _MISSING_HASH,
            "layer_statuses": layer_statuses,
            "layer_artifact_hashes": layer_artifact_hashes,
        }
    else:
        external_validation = validate_external_evidence_packet(
            external_evidence,
            expected_local_harness_report_hash=local_completion_audit_report_hash,
            expected_operator_execution_authority_pin=(operator_execution_authority_pin),
        )
    report = {
        "report_type": "issue20_oauth_mcp_harness",
        "status": "passed" if metrics["deterministic_fake_e2e_passed"] else "failed",
        "implementation_base_hash": local_context.implementation_base_hash,
        "metrics": metrics,
        "safe_outputs": {
            **local_safe_outputs,
            "local_completion_audit_report_hash": local_completion_audit_report_hash,
            "actor_context_contract_hash": _repository_contract_hash(_ACTOR_CONTEXT_CONTRACT_PATHS),
            "documentation_contract_hash": _repository_contract_hash(_DOCUMENTATION_CONTRACT_PATHS),
            "issue20_completion_journey_manifest_hash": sha256_json(_ISSUE20_COMPLETION_JOURNEYS),
            "external_evidence_packet_hash": external_validation["packet_hash"],
            "live_postgresql_artifact_hash": external_validation["layer_artifact_hashes"][
                "live_postgresql"
            ],
            "operator_cli_postgresql_artifact_hash": external_validation["layer_artifact_hashes"][
                "operator_cli_postgresql"
            ],
            "production_container_lifecycle_artifact_hash": external_validation[
                "layer_artifact_hashes"
            ]["production_container_lifecycle"],
            "mcp_inspector_artifact_hash": external_validation["layer_artifact_hashes"][
                "mcp_inspector"
            ],
            "live_chatgpt_google_artifact_hash": external_validation["layer_artifact_hashes"][
                "live_chatgpt_google"
            ],
            "reviewer_gate_artifact_hash": external_validation["layer_artifact_hashes"][
                "reviewer_gate"
            ],
            "completion_audit_artifact_hash": external_validation["layer_artifact_hashes"][
                "completion_audit"
            ],
            "external_evidence_blocker_count": external_validation["blocker_count"],
        },
        "evidence_layers": {
            "deterministic_fake_http_e2e_status": (
                "passed" if metrics["deterministic_fake_e2e_passed"] else "failed"
            ),
            "function_execution_status": (
                "passed" if metrics["function_test_execution_verified"] else "failed"
            ),
            "live_postgresql_rollback_status": external_validation["layer_statuses"][
                "live_postgresql"
            ],
            "operator_cli_postgresql_status": external_validation["layer_statuses"][
                "operator_cli_postgresql"
            ],
            "production_container_lifecycle_status": external_validation["layer_statuses"][
                "production_container_lifecycle"
            ],
            "mcp_inspector_remote_status": external_validation["layer_statuses"]["mcp_inspector"],
            "live_https_chatgpt_google_status": external_validation["layer_statuses"][
                "live_chatgpt_google"
            ],
            "reviewer_gate_status": external_validation["layer_statuses"]["reviewer_gate"],
            "completion_audit_status": external_validation["layer_statuses"]["completion_audit"],
        },
        "claim_boundary": {
            "supports_deterministic_fake_oauth_mcp_e2e_claim": metrics[
                "deterministic_fake_e2e_passed"
            ],
            "supports_live_postgresql_rollback_claim": external_validation["layer_statuses"][
                "live_postgresql"
            ]
            == "passed",
            "supports_operator_cli_postgresql_claim": external_validation["layer_statuses"][
                "operator_cli_postgresql"
            ]
            == "passed",
            "supports_production_container_lifecycle_claim": external_validation["layer_statuses"][
                "production_container_lifecycle"
            ]
            == "passed",
            "supports_mcp_inspector_remote_claim": external_validation["layer_statuses"][
                "mcp_inspector"
            ]
            == "passed",
            "supports_live_https_chatgpt_google_claim": external_validation["layer_statuses"][
                "live_chatgpt_google"
            ]
            == "passed",
            "supports_external_evidence_packet_contract_claim": external_validation["passed"],
            "supports_issue20_closure_claim": False,
            "requires_independent_issue20_completion_audit": True,
            "supports_production_ready_claim": False,
        },
    }
    report["validation"] = validate_report(
        report,
        external_evidence=external_evidence,
        operator_execution_authority_pin=operator_execution_authority_pin,
        production_container_lifecycle_evidence=production_container_lifecycle_evidence,
        _local_completion_context=local_context,
    )
    return report


def _build_local_safe_outputs(
    *,
    evidence: Mapping[str, Any],
    onboarding: Mapping[str, Any],
    execution: Mapping[str, Any],
    execution_validation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "implementation_contract_hash": issue20_implementation_contract_hash(ROOT),
        "manifest_hash": onboarding["manifest_hash"],
        "changed_function_set_hash": onboarding["changed_function_set_hash"],
        "scenario_contract_hash": _safe_hash(evidence.get("scenario_contract_hash")),
        "http_exchange_shape_hash": _safe_hash(evidence.get("http_exchange_shape_hash")),
        "audit_lineage_shape_hash": _safe_hash(evidence.get("audit_lineage_shape_hash")),
        "negotiated_protocol_version_hash": _safe_hash(
            evidence.get("negotiated_protocol_version_hash")
        ),
        "supported_protocol_matrix_hash": _safe_hash(
            evidence.get("supported_protocol_matrix_hash")
        ),
        "manifest_test_set_hash": _safe_hash(execution.get("test_set_hash")),
        "executed_test_set_hash": _safe_hash(execution.get("executed_test_set_hash")),
        "function_coverage_pairs_hash": _safe_hash(execution.get("coverage_pairs_hash")),
        "function_entry_count": onboarding["function_entry_count"],
        "onboarded_function_count": onboarding["onboarded_function_count"],
        "pending_function_count": onboarding["pending_function_count"],
        "changed_function_count": onboarding["changed_function_count"],
        "test_id_count": onboarding["test_id_count"],
        "manifest_requested_test_count": _safe_count(execution.get("requested_test_count")),
        "manifest_resolved_test_count": _safe_count(execution.get("resolved_test_count")),
        "manifest_run_count": _safe_count(execution.get("run_count")),
        "manifest_pass_count": _safe_count(execution.get("pass_count")),
        "manifest_skip_count": _safe_count(execution.get("skip_count")),
        "manifest_failure_count": _safe_count(execution.get("failure_count")),
        "manifest_error_count": _safe_count(execution.get("error_count")),
        "manifest_expected_failure_count": _safe_count(execution.get("expected_failure_count")),
        "manifest_unexpected_success_count": _safe_count(execution.get("unexpected_success_count")),
        "manifest_resolution_blocker_count": _safe_count(execution.get("resolution_blocker_count")),
        "manifest_covered_function_count": _safe_count(execution.get("covered_function_count")),
        "manifest_checked_pair_count": _safe_count(execution_validation.get("checked_pair_count")),
        "manifest_execution_blocker_count": len(execution_validation["blockers"]),
        "http_exchange_count": _safe_count(evidence.get("http_exchange_count")),
        "negative_case_count": _safe_count(evidence.get("negative_case_count")),
        "rollback_case_count": _safe_count(evidence.get("rollback_case_count")),
        "audit_event_count": _safe_count(evidence.get("audit_event_count")),
    }


def _local_completion_audit_report_hash(
    *,
    implementation_base_hash: str,
    metrics: Mapping[str, Any],
    safe_outputs: Mapping[str, Any],
) -> str:
    return sha256_json(
        {
            "binding_type": "issue20_pre_external_local_harness_evidence_v1",
            "implementation_base_hash": implementation_base_hash,
            "metrics": {key: metrics.get(key) for key in REQUIRED_METRICS},
            "safe_outputs": {
                key: safe_outputs.get(key) for key in _LOCAL_COMPLETION_SAFE_OUTPUT_FIELDS
            },
        }
    )


def _repository_contract_hash(paths: Sequence[str], *, root: Path = ROOT) -> str:
    file_hashes = _repository_contract_file_hashes(paths, root=root)
    return sha256_json(file_hashes) if file_hashes else _MISSING_HASH


def _repository_contract_file_hashes(paths: Sequence[str], *, root: Path = ROOT) -> dict[str, str]:
    try:
        resolved_root = root.resolve(strict=True)
    except OSError:
        return {}
    file_hashes: dict[str, str] = {}
    for relative_path in paths:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            return {}
        path = root / relative
        try:
            file_stat = path.lstat()
            resolved_path = path.resolve(strict=True)
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return {}
        if (
            stat.S_ISLNK(file_stat.st_mode)
            or not stat.S_ISREG(file_stat.st_mode)
            or not resolved_path.is_relative_to(resolved_root)
        ):
            return {}
        file_hashes[relative_path] = sha256_json(text)
    return file_hashes


def _issue20_expected_completion_document_texts(
    texts: Mapping[str, str],
) -> dict[str, str]:
    if set(texts) != set(_COMPLETION_STATE_CONTRACT_PATHS):
        return {}
    board_text = texts["docs/implementation-task-breakdown.md"]
    if (
        board_text.count(_ISSUE20_BOARD_OPEN_MARKER) != 1
        or board_text.count(_ISSUE20_BOARD_COMPLETE_MARKER) != 0
    ):
        return {}
    semantics = _issue20_completion_document_semantics(texts)
    open_statuses = semantics.get("completion_document_open")
    if not isinstance(open_statuses, Mapping) or any(
        open_statuses.get(path) is not True for path in _ISSUE20_COMPLETION_MARKERS_BY_PATH
    ):
        return {}
    readme = texts["README.md"]
    if readme.count(_ISSUE20_README_OPEN_MARKER) != 1:
        return {}
    completed_readme = readme.replace(
        _ISSUE20_README_OPEN_MARKER,
        _ISSUE20_README_TRANSITION_SENTENCE,
        1,
    )
    completed_board = board_text.replace(
        _ISSUE20_BOARD_OPEN_MARKER,
        _ISSUE20_BOARD_COMPLETE_MARKER,
        1,
    )
    for before, after in _ISSUE20_BOARD_COMPLETION_REPLACEMENTS:
        if completed_board.count(before) != 1:
            return {}
        completed_board = completed_board.replace(before, after, 1)
    goal = texts["docs/agent-goals/system-backbone-agent.md"]
    if (
        goal.count(_ISSUE20_GOAL_OPEN_EXTERNAL_STATE) != 1
        or goal.count(_ISSUE20_GOAL_OPEN_NEXT_ACTION) != 1
    ):
        return {}
    completed_goal = goal.replace(
        _ISSUE20_GOAL_OPEN_EXTERNAL_STATE,
        _ISSUE20_GOAL_COMPLETE_EXTERNAL_STATE,
        1,
    ).replace(
        _ISSUE20_GOAL_OPEN_NEXT_ACTION,
        _ISSUE20_GOAL_COMPLETE_NEXT_ACTION,
        1,
    )
    handoff = texts["docs/agent-goals/handoff-log.md"]
    verification = texts["docs/issue20-account-system-verification-status.md"]
    verification_record_start = "帳號系統已有相當完整的 repository-side 安全測試。Google 只驗證人，"
    if (
        verification.count(_ISSUE20_VERIFICATION_OPEN_MARKER) != 1
        or verification.count(verification_record_start) != 1
    ):
        return {}
    completed_verification = verification.replace(
        _ISSUE20_VERIFICATION_OPEN_MARKER,
        _ISSUE20_VERIFICATION_COMPLETE_MARKERS[0],
        1,
    ).replace(
        verification_record_start,
        "\n".join(
            (
                _ISSUE20_VERIFICATION_PRE_CLOSURE_HEADING,
                "",
                verification_record_start,
            )
        ),
        1,
    )
    completed_verification = "\n".join(
        (
            completed_verification.rstrip(),
            "",
            _ISSUE20_VERIFICATION_COMPLETE_HEADING,
            "",
            *_ISSUE20_VERIFICATION_COMPLETE_MARKERS[1:],
            "",
        )
    )
    completed_texts = {
        "README.md": "\n".join(
            (
                completed_readme.rstrip(),
                "",
                _ISSUE20_README_COMPLETE_HEADING,
                "",
                _ISSUE20_README_COMPLETE_MARKER,
                "",
            )
        ),
        "docs/implementation-task-breakdown.md": completed_board,
        "docs/agent-goals/system-backbone-agent.md": completed_goal,
        "docs/agent-goals/handoff-log.md": "\n".join(
            (
                handoff.rstrip(),
                "",
                _ISSUE20_HANDOFF_COMPLETE_HEADING,
                "",
                _ISSUE20_HANDOFF_COMPLETE_MARKER,
                "",
            )
        ),
        "docs/issue20-account-system-verification-status.md": completed_verification,
    }
    completed_semantics = _issue20_completion_document_semantics(completed_texts)
    complete_statuses = completed_semantics.get("completion_document_complete")
    if (
        completed_semantics.get("board_completion_coherent") is not True
        or not isinstance(complete_statuses, Mapping)
        or any(
            complete_statuses.get(path) is not True for path in _ISSUE20_COMPLETION_MARKERS_BY_PATH
        )
    ):
        return {}
    return completed_texts


def _issue20_completion_state_projection(*, root: Path = ROOT) -> dict[str, Any]:
    file_hashes = _repository_contract_file_hashes(
        _COMPLETION_STATE_CONTRACT_PATHS,
        root=root,
    )
    if set(file_hashes) != set(_COMPLETION_STATE_CONTRACT_PATHS):
        return {}
    try:
        texts = {
            relative_path: (root / relative_path).read_text(encoding="utf-8")
            for relative_path in _COMPLETION_STATE_CONTRACT_PATHS
        }
    except (OSError, UnicodeError):
        return {}
    expected_completion_texts = _issue20_expected_completion_document_texts(texts)
    board_lines = texts["docs/implementation-task-breakdown.md"].splitlines()
    checkbox_lines = [line for line in board_lines if re.fullmatch(r"- \[[ x]\] .+", line)]
    non_issue20_checkbox_lines = [
        line
        for line in checkbox_lines
        if line
        not in {
            _ISSUE20_BOARD_OPEN_MARKER,
            _ISSUE20_BOARD_COMPLETE_MARKER,
        }
    ]
    issue41_lines = [line for line in checkbox_lines if line == _ISSUE41_BOARD_OPEN_MARKER]
    completion_semantics = _issue20_completion_document_semantics(texts)
    normalized_readme = re.sub(r"\s+", " ", texts["README.md"])
    production_subject = (
        r"(?:FormOwl(?:\s+(?:system|service|application|platform|deployment|release))?"
        r"|the\s+(?:FormOwl\s+)?(?:system|service|application|platform|deployment|release)"
        r"|this\s+(?:system|service|application|platform|deployment|release|build)"
        r"|it|we)"
    )
    affirmative_production_patterns = (
        re.compile(
            rf"\b{production_subject}\s+"
            r"(?:is|are|was|were|became|becomes|can be considered)\s+"
            r"(?:(?:now|fully|officially)\s+)?"
            r"(?:production[- ]ready|ready for production)\b",
            re.IGNORECASE,
        ),
        re.compile(
            rf"\b{production_subject}\s+(?:has|have)\s+"
            r"(?:achieved|reached|established|confirmed)\s+production readiness\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:production readiness|readiness for production)\s+"
            r"(?:is|was|has been)\s+"
            r"(?:achieved|approved|complete|confirmed|established)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:^|[.!?]\s+)(?:status:\s*)?" r"(?:production[- ]ready|ready for production)\b",
            re.IGNORECASE,
        ),
    )
    affirmative_production_lines = sorted(
        {
            match.group(0).strip()
            for pattern in affirmative_production_patterns
            for match in pattern.finditer(normalized_readme)
        }
    )
    return {
        "file_hashes": file_hashes,
        "expected_completion_file_hashes": {
            relative_path: sha256_json(text)
            for relative_path, text in expected_completion_texts.items()
        },
        "board_open_count": board_lines.count(_ISSUE20_BOARD_OPEN_MARKER),
        "board_complete_count": board_lines.count(_ISSUE20_BOARD_COMPLETE_MARKER),
        **completion_semantics,
        "non_issue20_checkbox_manifest_hash": sha256_json(non_issue20_checkbox_lines),
        "issue41_checkbox_hash": (
            sha256_json(issue41_lines[0]) if len(issue41_lines) == 1 else _MISSING_HASH
        ),
        "production_ready_assertion_manifest_hash": sha256_json(affirmative_production_lines),
    }


def _issue20_completion_document_semantics(
    texts: Mapping[str, str],
) -> dict[str, Any]:
    marker_counts = {
        relative_path: {
            marker: texts.get(relative_path, "").splitlines().count(marker) for marker in markers
        }
        for relative_path, markers in _ISSUE20_COMPLETION_MARKERS_BY_PATH.items()
    }
    board = texts.get("docs/implementation-task-breakdown.md", "")
    readme = texts.get("README.md", "")
    goal = texts.get("docs/agent-goals/system-backbone-agent.md", "")
    handoff = texts.get("docs/agent-goals/handoff-log.md", "")
    verification = texts.get(
        "docs/issue20-account-system-verification-status.md",
        "",
    )
    board_lines = board.splitlines()
    readme_lines = readme.splitlines()
    goal_lines = goal.splitlines()
    handoff_lines = handoff.splitlines()
    verification_lines = verification.splitlines()
    handoff_final_section = handoff.rsplit("\n## ", 1)[-1] if "\n## " in handoff else handoff
    readme_final_section = readme.rsplit("\n## ", 1)[-1] if "\n## " in readme else readme
    verification_final_section = (
        verification.rsplit("\n## ", 1)[-1] if "\n## " in verification else verification
    )
    closure_prohibition_patterns = re.compile(
        r"\bIssue #20\s+(?:(?:remains?|stays?|is)\s+"
        r"(?:open|unfinished|unresolved|incomplete|unchecked)"
        r"|(?:must|should)\s+(?:remain|stay)\s+"
        r"(?:open|unfinished|unresolved|incomplete|unchecked))\b"
        r"|\b(?:Keep|Leave)\s+Issue #20\s+"
        r"(?:open|unfinished|unresolved|incomplete|unchecked)\b"
        r"|\bIssue #20\s+(?:(?:must|should|may|can)\s+not"
        r"|cannot|can't|mustn't|shouldn't)\s+(?:be\s+)?"
        r"(?:closed|completed|resolved|finalized)\b"
        r"|\b(?:Do not|Don't|Never)\s+"
        r"(?:close|complete|resolve|finalize)\s+Issue #20\b"
        r"|\bIssue #20\s+is\s+not\s+(?:ready|eligible|approved)\s+"
        r"(?:to\s+(?:close|complete|resolve|finalize)"
        r"|for\s+(?:closure|completion|resolution|finalization))\b"
        r"|\bIssue #20\s+(?:closure|completion|resolution|finalization)\s+"
        r"(?:is|remains)\s+(?:blocked|prohibited|forbidden|not allowed)\b"
        r"|Issue #20 仍為 open",
        re.IGNORECASE,
    )
    readme_open_assertions = closure_prohibition_patterns.findall(readme)
    handoff_open_assertions = closure_prohibition_patterns.findall(handoff_final_section)
    board_completion_coherent = (
        board_lines.count(_ISSUE20_BOARD_OPEN_MARKER) == 0
        and board_lines.count(_ISSUE20_BOARD_COMPLETE_MARKER) == 1
        and all(board_lines.count(marker) == 1 for marker in _ISSUE20_BOARD_COMPLETE_STATE_MARKERS)
        and closure_prohibition_patterns.search(board) is None
        and all(before not in board for before, _after in _ISSUE20_BOARD_COMPLETION_REPLACEMENTS)
    )
    goal_complete = (
        all(goal_lines.count(marker) == 1 for marker in _ISSUE20_GOAL_COMPLETE_MARKERS)
        and goal.count(_ISSUE20_GOAL_COMPLETE_EXTERNAL_STATE) == 1
        and goal.count(_ISSUE20_GOAL_COMPLETE_NEXT_ACTION) == 1
        and _ISSUE20_GOAL_OPEN_EXTERNAL_STATE not in goal
        and _ISSUE20_GOAL_OPEN_NEXT_ACTION not in goal
        and closure_prohibition_patterns.search(goal) is None
    )
    handoff_complete = (
        handoff_lines.count(_ISSUE20_HANDOFF_COMPLETE_HEADING) == 1
        and handoff_lines.count(_ISSUE20_HANDOFF_COMPLETE_MARKER) == 1
        and bool(handoff_lines)
        and handoff_lines[-1] == _ISSUE20_HANDOFF_COMPLETE_MARKER
        and closure_prohibition_patterns.search(handoff_final_section) is None
        and "`not_supplied`" not in handoff_final_section
        and "unchecked" not in handoff_final_section.casefold()
    )
    verification_complete = (
        all(
            verification_lines.count(marker) == 1
            for marker in _ISSUE20_VERIFICATION_COMPLETE_MARKERS
        )
        and verification_lines.count(_ISSUE20_VERIFICATION_PRE_CLOSURE_HEADING) == 1
        and verification_lines.count(_ISSUE20_VERIFICATION_COMPLETE_HEADING) == 1
        and bool(verification_lines)
        and verification_lines[-1] == _ISSUE20_VERIFICATION_COMPLETE_MARKERS[-1]
        and _ISSUE20_VERIFICATION_OPEN_MARKER not in verification_lines
        and closure_prohibition_patterns.search(verification_final_section) is None
    )
    readme_complete = (
        readme_lines.count(_ISSUE20_README_COMPLETE_HEADING) == 1
        and readme_lines.count(_ISSUE20_README_COMPLETE_MARKER) == 1
        and bool(readme_lines)
        and readme_lines[-1] == _ISSUE20_README_COMPLETE_MARKER
        and closure_prohibition_patterns.search(readme_final_section) is None
    )
    completion_document_complete = {
        "README.md": readme_complete,
        "docs/agent-goals/system-backbone-agent.md": goal_complete,
        "docs/agent-goals/handoff-log.md": handoff_complete,
        "docs/issue20-account-system-verification-status.md": (verification_complete),
    }
    completion_document_open = {
        "README.md": (
            all(count == 0 for count in marker_counts["README.md"].values())
            and "Issue #20 closure state: `complete`" not in readme
            and readme.count(_ISSUE20_README_OPEN_MARKER) == 1
            and len(readme_open_assertions) == 1
        ),
        "docs/agent-goals/system-backbone-agent.md": (
            goal_lines.count(_ISSUE20_GOAL_OPEN_MARKERS[0]) == 1
            and goal_lines.count(_ISSUE20_GOAL_OPEN_MARKERS[1]) == 1
            and _ISSUE20_GOAL_OPEN_MARKERS[2] in goal
            and all(
                count == 0
                for count in marker_counts["docs/agent-goals/system-backbone-agent.md"].values()
            )
        ),
        "docs/agent-goals/handoff-log.md": (
            all(count == 0 for count in marker_counts["docs/agent-goals/handoff-log.md"].values())
            and (
                re.search(
                    r"Issue #20 remains open and\s+unchecked",
                    handoff_final_section,
                    re.IGNORECASE,
                )
                is not None
            )
            and len(handoff_open_assertions) == 1
        ),
        "docs/issue20-account-system-verification-status.md": (
            verification_lines.count(_ISSUE20_VERIFICATION_OPEN_MARKER) == 1
            and all(
                count == 0
                for count in marker_counts[
                    "docs/issue20-account-system-verification-status.md"
                ].values()
            )
        ),
    }
    return {
        "completion_marker_counts": marker_counts,
        "completion_document_open": completion_document_open,
        "completion_document_complete": completion_document_complete,
        "board_completion_coherent": board_completion_coherent,
    }


def build_issue20_preclosure_manifest(
    external_evidence: Any,
    *,
    expected_local_harness_report_hash: str,
    expected_operator_execution_authority_pin: Mapping[str, Any],
    operator_attested: bool,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Freeze reviewed evidence and the still-open mutable completion state."""

    if operator_attested is not True or not isinstance(external_evidence, Mapping):
        return {}
    layers = external_evidence.get("layers")
    if not isinstance(layers, Mapping):
        return {}
    reviewer_layer = layers.get("reviewer_gate")
    completion_layer = layers.get("completion_audit")
    if not isinstance(reviewer_layer, Mapping) or not isinstance(completion_layer, Mapping):
        return {}
    state = _issue20_completion_state_projection(root=root)
    manifest = {
        "artifact_type": _PRE_CLOSURE_MANIFEST_TYPE,
        "schema_version": _PRE_CLOSURE_MANIFEST_SCHEMA_VERSION,
        "status": "passed",
        "operator_attested": True,
        "closure_transition_plan_hash": _CLOSURE_TRANSITION_PLAN_HASH,
        "reviewer_gate_governance_hash": _repository_contract_hash(
            _REVIEWER_GATE_GOVERNANCE_PATHS,
            root=root,
        ),
        "external_evidence_packet_hash": _hash_external_packet(external_evidence),
        "preclosure_documentation_contract_hash": _repository_contract_hash(
            _PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
            root=root,
        ),
        "reviewer_gate_artifact_hash": reviewer_layer.get("evidence_artifact_hash"),
        "completion_audit_artifact_hash": completion_layer.get("evidence_artifact_hash"),
        "mutable_document_before_hashes": state.get("file_hashes", {}),
        "mutable_document_expected_after_hashes": state.get(
            "expected_completion_file_hashes",
            {},
        ),
        "non_issue20_checkbox_manifest_hash": state.get(
            "non_issue20_checkbox_manifest_hash",
            _MISSING_HASH,
        ),
        "issue41_checkbox_hash": state.get("issue41_checkbox_hash", _MISSING_HASH),
        "production_ready_assertion_manifest_hash": state.get(
            "production_ready_assertion_manifest_hash",
            _MISSING_HASH,
        ),
        "attestations": {name: True for name in sorted(_PRE_CLOSURE_MANIFEST_ATTESTATIONS)},
    }
    manifest["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": "issue20_preclosure_manifest_v1",
            "manifest_without_artifact_hash": manifest,
        }
    )
    validation = validate_issue20_preclosure_manifest(
        manifest,
        external_evidence=external_evidence,
        expected_local_harness_report_hash=expected_local_harness_report_hash,
        expected_operator_execution_authority_pin=(expected_operator_execution_authority_pin),
        root=root,
    )
    return manifest if validation["passed"] is True else {}


def validate_issue20_preclosure_manifest(
    manifest: Any,
    *,
    external_evidence: Any,
    expected_local_harness_report_hash: str,
    expected_operator_execution_authority_pin: Mapping[str, Any],
    root: Path = ROOT,
    require_current_before_state: bool = True,
) -> dict[str, Any]:
    """Validate frozen pre-closure evidence without rebuilding reviewer artifacts."""

    blockers: list[str] = []
    value = dict(manifest) if isinstance(manifest, Mapping) else {}
    _exact_keys(
        value,
        _PRE_CLOSURE_MANIFEST_FIELDS,
        "issue20_preclosure_manifest",
        blockers,
    )
    if value.get("artifact_type") != _PRE_CLOSURE_MANIFEST_TYPE:
        blockers.append("preclosure manifest type mismatch")
    if value.get("schema_version") != _PRE_CLOSURE_MANIFEST_SCHEMA_VERSION:
        blockers.append("preclosure manifest schema version mismatch")
    if value.get("status") != "passed":
        blockers.append("preclosure manifest did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("preclosure manifest operator attestation is missing")
    for field in (
        "closure_transition_plan_hash",
        "reviewer_gate_governance_hash",
        "external_evidence_packet_hash",
        "preclosure_documentation_contract_hash",
        "reviewer_gate_artifact_hash",
        "completion_audit_artifact_hash",
        "non_issue20_checkbox_manifest_hash",
        "issue41_checkbox_hash",
        "production_ready_assertion_manifest_hash",
        "evidence_artifact_hash",
    ):
        if not _is_sha256(value.get(field)) or value.get(field) == _MISSING_HASH:
            blockers.append(f"preclosure manifest hash is invalid: {field}")
    if value.get("closure_transition_plan_hash") != _CLOSURE_TRANSITION_PLAN_HASH:
        blockers.append("preclosure manifest transition plan mismatch")
    if value.get("production_ready_assertion_manifest_hash") != sha256_json([]):
        blockers.append("preclosure production-readiness assertion is forbidden")
    expected_reviewer_governance_hash = _repository_contract_hash(
        _REVIEWER_GATE_GOVERNANCE_PATHS,
        root=root,
    )
    if value.get("reviewer_gate_governance_hash") != expected_reviewer_governance_hash:
        blockers.append("preclosure reviewer-gate governance drifted")
    before_hashes = value.get("mutable_document_before_hashes")
    if not isinstance(before_hashes, Mapping):
        blockers.append("preclosure mutable document hashes must be an object")
        before_hashes_dict: dict[str, Any] = {}
    else:
        before_hashes_dict = dict(before_hashes)
        _exact_keys(
            before_hashes_dict,
            set(_COMPLETION_STATE_CONTRACT_PATHS),
            "issue20_preclosure_manifest.mutable_document_before_hashes",
            blockers,
        )
        for path, digest in before_hashes_dict.items():
            if not _is_sha256(digest) or digest == _MISSING_HASH:
                blockers.append(f"preclosure mutable document hash is invalid: {path}")
    expected_after_hashes = value.get("mutable_document_expected_after_hashes")
    if not isinstance(expected_after_hashes, Mapping):
        blockers.append("preclosure expected mutable document hashes must be an object")
        expected_after_hashes_dict: dict[str, Any] = {}
    else:
        expected_after_hashes_dict = dict(expected_after_hashes)
        _exact_keys(
            expected_after_hashes_dict,
            set(_COMPLETION_STATE_CONTRACT_PATHS),
            "issue20_preclosure_manifest.mutable_document_expected_after_hashes",
            blockers,
        )
        for path, digest in expected_after_hashes_dict.items():
            if not _is_sha256(digest) or digest == _MISSING_HASH:
                blockers.append(f"preclosure expected mutable document hash is invalid: {path}")
    attestations = value.get("attestations")
    if not isinstance(attestations, Mapping):
        blockers.append("preclosure attestations must be an object")
    else:
        _exact_keys(
            attestations,
            _PRE_CLOSURE_MANIFEST_ATTESTATIONS,
            "issue20_preclosure_manifest.attestations",
            blockers,
        )
        for name in _PRE_CLOSURE_MANIFEST_ATTESTATIONS:
            if attestations.get(name) is not True:
                blockers.append(f"preclosure attestation must be true: {name}")
    external_validation = validate_external_evidence_packet(
        external_evidence,
        expected_local_harness_report_hash=expected_local_harness_report_hash,
        expected_operator_execution_authority_pin=(expected_operator_execution_authority_pin),
        root=root,
    )
    if external_validation["passed"] is not True:
        blockers.append("preclosure external evidence is not accepted")
    expected_packet_hash = _hash_external_packet(external_evidence)
    if value.get("external_evidence_packet_hash") != expected_packet_hash:
        blockers.append("preclosure external packet binding mismatch")
    layers = (
        dict(external_evidence.get("layers"))
        if isinstance(external_evidence, Mapping)
        and isinstance(external_evidence.get("layers"), Mapping)
        else {}
    )
    reviewer_layer = layers.get("reviewer_gate")
    completion_layer = layers.get("completion_audit")
    if (
        not isinstance(reviewer_layer, Mapping)
        or reviewer_layer.get("status") != "passed"
        or reviewer_layer.get("reviewer_count") != 3
        or reviewer_layer.get("agreement_count") != 3
        or reviewer_layer.get("blocking_finding_count") != 0
        or value.get("reviewer_gate_artifact_hash") != reviewer_layer.get("evidence_artifact_hash")
    ):
        blockers.append("preclosure reviewer gate is not bound to 3/3 AGREE")
    if (
        not isinstance(completion_layer, Mapping)
        or completion_layer.get("status") != "passed"
        or completion_layer.get("blocking_finding_count") != 0
        or value.get("completion_audit_artifact_hash")
        != completion_layer.get("evidence_artifact_hash")
    ):
        blockers.append("preclosure completion audit is not bound and passed")
    expected_documentation_hash = _repository_contract_hash(
        _PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
        root=root,
    )
    if value.get("preclosure_documentation_contract_hash") != expected_documentation_hash:
        blockers.append("preclosure substantive documentation drifted")
    if require_current_before_state:
        state = _issue20_completion_state_projection(root=root)
        if state.get("file_hashes") != before_hashes_dict:
            blockers.append("preclosure mutable document bytes do not match")
        if state.get("expected_completion_file_hashes") != expected_after_hashes_dict:
            blockers.append("preclosure expected completion document bytes do not match")
        if state.get("board_open_count") != 1 or state.get("board_complete_count") != 0:
            blockers.append("preclosure issue #20 board state is not uniquely open")
        marker_counts = state.get("completion_marker_counts")
        if not isinstance(marker_counts, Mapping) or any(
            not isinstance(marker_counts.get(path), Mapping)
            or any(count != 0 for count in marker_counts[path].values())
            for path in _ISSUE20_COMPLETION_MARKERS_BY_PATH
        ):
            blockers.append("preclosure completion marker was applied early")
        open_statuses = state.get("completion_document_open")
        if not isinstance(open_statuses, Mapping) or any(
            open_statuses.get(path) is not True for path in _ISSUE20_COMPLETION_MARKERS_BY_PATH
        ):
            blockers.append("preclosure mutable documents are not coherently open")
        for field in (
            "non_issue20_checkbox_manifest_hash",
            "issue41_checkbox_hash",
            "production_ready_assertion_manifest_hash",
        ):
            if value.get(field) != state.get(field):
                blockers.append(f"preclosure semantic manifest mismatch: {field}")
    expected_artifact_hash = sha256_json(
        {
            "binding_type": "issue20_preclosure_manifest_v1",
            "manifest_without_artifact_hash": {
                key: item for key, item in value.items() if key != "evidence_artifact_hash"
            },
        }
    )
    if value.get("evidence_artifact_hash") != expected_artifact_hash:
        blockers.append("preclosure artifact binding mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("preclosure manifest contains sensitive material")
    passed = not blockers
    return {
        "artifact_type": "issue20_preclosure_manifest_validation_v1",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "blocker_count": len(blockers),
        "preclosure_manifest_hash": _safe_hash(value.get("evidence_artifact_hash")),
        "closure_transition_plan_hash": _CLOSURE_TRANSITION_PLAN_HASH,
        "external_evidence_packet_hash": expected_packet_hash,
        "preclosure_documentation_contract_hash": expected_documentation_hash,
    }


def build_issue20_completion_transition(
    external_evidence: Any,
    *,
    preclosure_manifest: Any,
    expected_local_harness_report_hash: str,
    expected_operator_execution_authority_pin: Mapping[str, Any],
    operator_attested: bool,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Build the self-bound post-audit completion-state transition artifact."""

    if (
        operator_attested is not True
        or not isinstance(external_evidence, Mapping)
        or not isinstance(preclosure_manifest, Mapping)
    ):
        return {}
    layers = external_evidence.get("layers")
    if not isinstance(layers, Mapping):
        return {}
    reviewer_layer = layers.get("reviewer_gate")
    completion_layer = layers.get("completion_audit")
    if not isinstance(reviewer_layer, Mapping) or not isinstance(completion_layer, Mapping):
        return {}
    state = _issue20_completion_state_projection(root=root)
    before_hashes = preclosure_manifest.get("mutable_document_before_hashes")
    transition = {
        "artifact_type": _COMPLETION_TRANSITION_TYPE,
        "schema_version": _COMPLETION_TRANSITION_SCHEMA_VERSION,
        "status": "passed",
        "operator_attested": True,
        "preclosure_manifest_hash": preclosure_manifest.get("evidence_artifact_hash"),
        "closure_transition_plan_hash": _CLOSURE_TRANSITION_PLAN_HASH,
        "reviewer_gate_governance_hash": _repository_contract_hash(
            _REVIEWER_GATE_GOVERNANCE_PATHS,
            root=root,
        ),
        "external_evidence_packet_hash": _hash_external_packet(external_evidence),
        "preclosure_documentation_contract_hash": _repository_contract_hash(
            _PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
            root=root,
        ),
        "completion_state_before_hashes_hash": sha256_json(before_hashes),
        "completion_state_after_hashes_hash": sha256_json(state.get("file_hashes", {})),
        "mutable_document_after_hashes": state.get("file_hashes", {}),
        "non_issue20_checkbox_manifest_hash": state.get(
            "non_issue20_checkbox_manifest_hash",
            _MISSING_HASH,
        ),
        "issue41_checkbox_hash": state.get("issue41_checkbox_hash", _MISSING_HASH),
        "production_ready_assertion_manifest_hash": state.get(
            "production_ready_assertion_manifest_hash",
            _MISSING_HASH,
        ),
        "reviewer_gate_artifact_hash": reviewer_layer.get("evidence_artifact_hash"),
        "completion_audit_artifact_hash": completion_layer.get("evidence_artifact_hash"),
        "attestations": {name: True for name in sorted(_COMPLETION_TRANSITION_ATTESTATIONS)},
    }
    transition["evidence_artifact_hash"] = sha256_json(
        {
            "binding_type": "issue20_post_audit_transition_v1",
            "transition_without_artifact_hash": transition,
        }
    )
    validation = validate_issue20_completion_transition(
        transition,
        external_evidence=external_evidence,
        preclosure_manifest=preclosure_manifest,
        expected_local_harness_report_hash=expected_local_harness_report_hash,
        expected_operator_execution_authority_pin=(expected_operator_execution_authority_pin),
        root=root,
    )
    return transition if validation["passed"] is True else {}


def validate_issue20_completion_transition(
    transition: Any,
    *,
    external_evidence: Any,
    preclosure_manifest: Any,
    expected_local_harness_report_hash: str,
    expected_operator_execution_authority_pin: Mapping[str, Any],
    root: Path = ROOT,
) -> dict[str, Any]:
    """Validate the only artifact allowed to support issue #20 closure."""

    blockers: list[str] = []
    value = dict(transition) if isinstance(transition, Mapping) else {}
    _exact_keys(
        value,
        _COMPLETION_TRANSITION_FIELDS,
        "issue20_completion_transition",
        blockers,
    )
    if value.get("artifact_type") != _COMPLETION_TRANSITION_TYPE:
        blockers.append("completion transition type mismatch")
    if value.get("schema_version") != _COMPLETION_TRANSITION_SCHEMA_VERSION:
        blockers.append("completion transition schema version mismatch")
    if value.get("status") != "passed":
        blockers.append("completion transition did not pass")
    if value.get("operator_attested") is not True:
        blockers.append("completion transition operator attestation is missing")
    for field in (
        "preclosure_manifest_hash",
        "closure_transition_plan_hash",
        "reviewer_gate_governance_hash",
        "external_evidence_packet_hash",
        "preclosure_documentation_contract_hash",
        "completion_state_before_hashes_hash",
        "completion_state_after_hashes_hash",
        "non_issue20_checkbox_manifest_hash",
        "issue41_checkbox_hash",
        "production_ready_assertion_manifest_hash",
        "reviewer_gate_artifact_hash",
        "completion_audit_artifact_hash",
        "evidence_artifact_hash",
    ):
        if not _is_sha256(value.get(field)) or value.get(field) == _MISSING_HASH:
            blockers.append(f"completion transition hash is invalid: {field}")
    attestations = value.get("attestations")
    if not isinstance(attestations, Mapping):
        blockers.append("completion transition attestations must be an object")
    else:
        _exact_keys(
            attestations,
            _COMPLETION_TRANSITION_ATTESTATIONS,
            "issue20_completion_transition.attestations",
            blockers,
        )
        for name in _COMPLETION_TRANSITION_ATTESTATIONS:
            if attestations.get(name) is not True:
                blockers.append(f"completion transition attestation must be true: {name}")
    preclosure_validation = validate_issue20_preclosure_manifest(
        preclosure_manifest,
        external_evidence=external_evidence,
        expected_local_harness_report_hash=expected_local_harness_report_hash,
        expected_operator_execution_authority_pin=(expected_operator_execution_authority_pin),
        root=root,
        require_current_before_state=False,
    )
    if preclosure_validation["passed"] is not True:
        blockers.append("completion transition frozen preclosure manifest is invalid")
    preclosure = dict(preclosure_manifest) if isinstance(preclosure_manifest, Mapping) else {}
    if value.get("preclosure_manifest_hash") != preclosure.get("evidence_artifact_hash"):
        blockers.append("completion transition preclosure manifest binding mismatch")
    if value.get("closure_transition_plan_hash") != _CLOSURE_TRANSITION_PLAN_HASH:
        blockers.append("completion transition plan mismatch")
    expected_reviewer_governance_hash = _repository_contract_hash(
        _REVIEWER_GATE_GOVERNANCE_PATHS,
        root=root,
    )
    if value.get("reviewer_gate_governance_hash") != expected_reviewer_governance_hash or value.get(
        "reviewer_gate_governance_hash"
    ) != preclosure.get("reviewer_gate_governance_hash"):
        blockers.append("completion transition reviewer-gate governance drifted")
    expected_packet_hash = _hash_external_packet(external_evidence)
    if value.get("external_evidence_packet_hash") != expected_packet_hash:
        blockers.append("completion transition external packet binding mismatch")
    layers = (
        dict(external_evidence.get("layers"))
        if isinstance(external_evidence, Mapping)
        and isinstance(external_evidence.get("layers"), Mapping)
        else {}
    )
    reviewer_layer = layers.get("reviewer_gate")
    completion_layer = layers.get("completion_audit")
    if not isinstance(reviewer_layer, Mapping) or value.get(
        "reviewer_gate_artifact_hash"
    ) != reviewer_layer.get("evidence_artifact_hash"):
        blockers.append("completion transition reviewer artifact binding mismatch")
    if not isinstance(completion_layer, Mapping) or value.get(
        "completion_audit_artifact_hash"
    ) != completion_layer.get("evidence_artifact_hash"):
        blockers.append("completion transition audit artifact binding mismatch")
    expected_preclosure_hash = _repository_contract_hash(
        _PRE_CLOSURE_DOCUMENTATION_CONTRACT_PATHS,
        root=root,
    )
    if value.get("preclosure_documentation_contract_hash") != expected_preclosure_hash or value.get(
        "preclosure_documentation_contract_hash"
    ) != preclosure.get("preclosure_documentation_contract_hash"):
        blockers.append("completion transition substantive documentation drifted")
    before_hashes = preclosure.get("mutable_document_before_hashes")
    if not isinstance(before_hashes, Mapping):
        blockers.append("completion transition before-state manifest is missing")
        before_hashes_dict: dict[str, Any] = {}
    else:
        before_hashes_dict = dict(before_hashes)
    expected_after_hashes = preclosure.get("mutable_document_expected_after_hashes")
    if not isinstance(expected_after_hashes, Mapping):
        blockers.append("completion transition expected after-state manifest is missing")
        expected_after_hashes_dict: dict[str, Any] = {}
    else:
        expected_after_hashes_dict = dict(expected_after_hashes)
    after_hashes = value.get("mutable_document_after_hashes")
    if not isinstance(after_hashes, Mapping):
        blockers.append("completion transition after-state manifest is missing")
        after_hashes_dict: dict[str, Any] = {}
    else:
        after_hashes_dict = dict(after_hashes)
        _exact_keys(
            after_hashes_dict,
            set(_COMPLETION_STATE_CONTRACT_PATHS),
            "issue20_completion_transition.mutable_document_after_hashes",
            blockers,
        )
        for path, digest in after_hashes_dict.items():
            if not _is_sha256(digest) or digest == _MISSING_HASH:
                blockers.append(f"completion transition after hash is invalid: {path}")
    state = _issue20_completion_state_projection(root=root)
    if after_hashes_dict != state.get("file_hashes"):
        blockers.append("completion transition after-state bytes do not match")
    if after_hashes_dict != expected_after_hashes_dict:
        blockers.append("completion transition does not match the governed exact document delta")
    if value.get("completion_state_before_hashes_hash") != sha256_json(before_hashes_dict):
        blockers.append("completion transition before-state hash mismatch")
    if value.get("completion_state_after_hashes_hash") != sha256_json(after_hashes_dict):
        blockers.append("completion transition after-state hash mismatch")
    if set(before_hashes_dict) != set(_COMPLETION_STATE_CONTRACT_PATHS) or any(
        before_hashes_dict.get(path) == after_hashes_dict.get(path)
        for path in _COMPLETION_STATE_CONTRACT_PATHS
    ):
        blockers.append("completion transition contains a partial mutable-doc update")
    if state.get("board_open_count") != 0 or state.get("board_complete_count") != 1:
        blockers.append("completion transition issue #20 checkbox is not uniquely complete")
    if state.get("board_completion_coherent") is not True:
        blockers.append("completion transition issue #20 board state is contradictory")
    marker_counts = state.get("completion_marker_counts")
    if not isinstance(marker_counts, Mapping) or any(
        not isinstance(marker_counts.get(path), Mapping)
        or any(count != 1 for count in marker_counts[path].values())
        for path in _ISSUE20_COMPLETION_MARKERS_BY_PATH
    ):
        blockers.append("completion transition completion markers are incomplete")
    completion_statuses = state.get("completion_document_complete")
    if not isinstance(completion_statuses, Mapping) or any(
        completion_statuses.get(path) is not True for path in _ISSUE20_COMPLETION_MARKERS_BY_PATH
    ):
        blockers.append("completion transition mutable documents are contradictory")
    for field in (
        "non_issue20_checkbox_manifest_hash",
        "issue41_checkbox_hash",
        "production_ready_assertion_manifest_hash",
    ):
        if value.get(field) != state.get(field) or value.get(field) != preclosure.get(field):
            blockers.append(f"completion transition semantic manifest changed: {field}")
    expected_artifact_hash = sha256_json(
        {
            "binding_type": "issue20_post_audit_transition_v1",
            "transition_without_artifact_hash": {
                key: item for key, item in value.items() if key != "evidence_artifact_hash"
            },
        }
    )
    if value.get("evidence_artifact_hash") != expected_artifact_hash:
        blockers.append("completion transition artifact binding mismatch")
    try:
        assert_safe_harness_report(value)
    except AssertionError:
        blockers.append("completion transition contains sensitive material")
    passed = not blockers
    return {
        "artifact_type": "issue20_completion_transition_validation_v1",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "supports_issue20_closure_claim": passed,
        "blocker_count": len(blockers),
        "completion_transition_artifact_hash": _safe_hash(value.get("evidence_artifact_hash")),
        "preclosure_manifest_hash": _safe_hash(preclosure.get("evidence_artifact_hash")),
        "closure_transition_plan_hash": _CLOSURE_TRANSITION_PLAN_HASH,
        "completion_state_before_hashes_hash": sha256_json(before_hashes_dict),
        "completion_state_after_hashes_hash": sha256_json(after_hashes_dict),
        "preclosure_documentation_contract_hash": expected_preclosure_hash,
        "external_evidence_packet_hash": expected_packet_hash,
        "reviewer_gate_artifact_hash": _safe_hash(value.get("reviewer_gate_artifact_hash")),
        "completion_audit_artifact_hash": _safe_hash(value.get("completion_audit_artifact_hash")),
    }


def validate_external_evidence_packet(
    packet: Any,
    *,
    expected_local_harness_report_hash: str | None = None,
    expected_operator_execution_authority_pin: Mapping[str, Any] | None = None,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Validate bounded operator evidence for every non-local closure gate."""

    layer_names = tuple(_EXTERNAL_LAYER_FIELDS)
    layer_statuses = {name: "not_supplied" for name in layer_names}
    layer_artifact_hashes = {name: _MISSING_HASH for name in layer_names}
    if packet is None:
        blockers = [f"external evidence layer was not supplied: {name}" for name in layer_names]
        return {
            "passed": False,
            "blockers": blockers,
            "blocker_count": len(blockers),
            "packet_hash": _MISSING_HASH,
            "layer_statuses": layer_statuses,
            "layer_artifact_hashes": layer_artifact_hashes,
        }

    packet_hash = _hash_external_packet(packet)
    packet_blockers: list[str] = []
    layer_blockers: dict[str, list[str]] = {name: [] for name in layer_names}
    if not isinstance(packet, Mapping):
        packet_blockers.append("external evidence packet must be an object")
        packet_dict: dict[str, Any] = {}
    else:
        packet_dict = dict(packet)
        _exact_keys(
            packet_dict,
            {"packet_type", "schema_version", "layers"},
            "external_evidence",
            packet_blockers,
        )
        if packet_dict.get("packet_type") != _EXTERNAL_PACKET_TYPE:
            packet_blockers.append("external evidence packet type mismatch")
        if packet_dict.get("schema_version") != _EXTERNAL_PACKET_SCHEMA_VERSION:
            packet_blockers.append("external evidence schema version mismatch")
        try:
            assert_safe_harness_report(packet_dict)
        except AssertionError:
            packet_blockers.append(
                "external evidence packet contains sensitive OAuth, transcript, path, or SQL material"
            )

    layers = packet_dict.get("layers")
    if not isinstance(layers, Mapping):
        packet_blockers.append("external evidence layers must be an object")
        layers_dict: dict[str, Any] = {}
    else:
        layers_dict = dict(layers)
        _exact_keys(layers_dict, set(layer_names), "external_evidence.layers", packet_blockers)

    for layer_name in layer_names:
        raw_layer = layers_dict.get(layer_name)
        blockers = layer_blockers[layer_name]
        if not isinstance(raw_layer, Mapping):
            blockers.append(f"external evidence layer must be an object: {layer_name}")
            continue
        layer = dict(raw_layer)
        _exact_keys(
            layer,
            set(_EXTERNAL_LAYER_FIELDS[layer_name]),
            f"external_evidence.layers.{layer_name}",
            blockers,
        )
        artifact_hash = layer.get("evidence_artifact_hash")
        if _is_sha256(artifact_hash) and artifact_hash != _MISSING_HASH:
            layer_artifact_hashes[layer_name] = str(artifact_hash)
        if layer.get("status") != "passed":
            blockers.append(f"external evidence layer did not pass: {layer_name}")
        if layer.get("operator_attested") is not True:
            blockers.append(f"external evidence operator attestation is missing: {layer_name}")
        _validate_external_hash_fields(layer_name, layer, blockers)
        _validate_external_attestations(layer_name, layer.get("attestations"), blockers)
        _validate_external_layer_counts(layer_name, layer, blockers)
        if layer_name == "live_postgresql":
            dedicated_validation = _live_postgresql.validate_live_postgresql_external_layer(layer)
            if dedicated_validation["passed"] is not True:
                blockers.append("live PostgreSQL dedicated validation failed")
        if layer_name == "operator_cli_postgresql":
            dedicated_validation = validate_operator_cli_postgresql_external_layer(
                layer,
                trusted_execution_authority_pin=(expected_operator_execution_authority_pin),
            )
            if dedicated_validation["passed"] is not True:
                blockers.append("operator CLI PostgreSQL dedicated validation failed")
        if layer_name == "production_container_lifecycle":
            dedicated_validation = validate_production_container_lifecycle_external_layer(layer)
            if dedicated_validation["passed"] is not True:
                blockers.append("production container lifecycle dedicated validation failed")
        if layer_name == "completion_audit":
            dedicated_validation = validate_completion_audit_external_layer(layer)
            if dedicated_validation["passed"] is not True:
                blockers.append("completion audit dedicated validation failed")
        if layer_name == "mcp_inspector":
            dedicated_validation = validate_mcp_inspector_external_layer(layer)
            if dedicated_validation["passed"] is not True:
                blockers.append("MCP Inspector dedicated validation failed")
        if layer_name == "live_chatgpt_google":
            dedicated_validation = validate_live_chatgpt_google_external_layer(layer)
            if dedicated_validation["passed"] is not True:
                blockers.append("live ChatGPT/Google dedicated validation failed")
        if layer_name == "reviewer_gate":
            dedicated_validation = validate_reviewer_gate_external_layer(layer)
            if dedicated_validation["passed"] is not True:
                blockers.append("reviewer-gate dedicated validation failed")

    source_commitment_owners: dict[str, list[str]] = {}
    for layer_name, field in _EXTERNAL_SOURCE_COMMITMENT_FIELDS:
        layer = layers_dict.get(layer_name)
        value = layer.get(field) if isinstance(layer, Mapping) else None
        if _is_sha256(value) and value != _MISSING_HASH:
            source_commitment_owners.setdefault(str(value), []).append(layer_name)
    for owners in source_commitment_owners.values():
        if len(owners) < 2:
            continue
        for layer_name in owners:
            layer_blockers[layer_name].append(
                "external evidence source commitments must be distinct"
            )

    public_artifact_owners: dict[str, list[str]] = {}
    for layer_name in layer_names:
        layer = layers_dict.get(layer_name)
        value = layer.get("evidence_artifact_hash") if isinstance(layer, Mapping) else None
        if _is_sha256(value) and value != _MISSING_HASH:
            public_artifact_owners.setdefault(str(value), []).append(layer_name)
    for value in set(source_commitment_owners) & set(public_artifact_owners):
        for layer_name in (
            *source_commitment_owners[value],
            *public_artifact_owners[value],
        ):
            layer_blockers[layer_name].append(
                "external evidence source commitments must be disjoint from public artifacts"
            )

    try:
        expected_implementation_contract_hash = issue20_implementation_contract_hash(root)
    except Exception:
        expected_implementation_contract_hash = None
        packet_blockers.append("external evidence implementation contract validation failed")
    if expected_implementation_contract_hash is not None:
        for layer_name in (
            "live_postgresql",
            "operator_cli_postgresql",
            "production_container_lifecycle",
            "completion_audit",
        ):
            layer = layers_dict.get(layer_name)
            if (
                isinstance(layer, Mapping)
                and layer.get("implementation_contract_hash")
                != expected_implementation_contract_hash
            ):
                layer_blockers[layer_name].append(
                    f"external evidence implementation contract mismatch: {layer_name}"
                )

    completion_layer = layers_dict.get("completion_audit")
    if isinstance(completion_layer, Mapping):
        expected_authority_pin_hash = (
            sha256_json(dict(expected_operator_execution_authority_pin))
            if isinstance(expected_operator_execution_authority_pin, Mapping)
            else None
        )
        operator_layer = layers_dict.get("operator_cli_postgresql")
        operator_pin_hash = (
            operator_layer.get("execution_authority_pin_hash")
            if isinstance(operator_layer, Mapping)
            else None
        )
        if (
            expected_authority_pin_hash is None
            or completion_layer.get("operator_execution_authority_pin_hash")
            != expected_authority_pin_hash
            or operator_pin_hash != expected_authority_pin_hash
        ):
            layer_blockers["completion_audit"].append(
                "completion audit execution authority pin binding mismatch"
            )
        expected_actor_context_hash = _repository_contract_hash(
            _ACTOR_CONTEXT_CONTRACT_PATHS,
            root=root,
        )
        expected_documentation_hash = _repository_contract_hash(
            _DOCUMENTATION_CONTRACT_PATHS,
            root=root,
        )
        if (
            not _is_sha256(expected_local_harness_report_hash)
            or expected_local_harness_report_hash == _MISSING_HASH
            or completion_layer.get("local_harness_report_hash")
            != expected_local_harness_report_hash
        ):
            layer_blockers["completion_audit"].append(
                "completion audit local harness binding mismatch"
            )
        if completion_layer.get("actor_context_contract_hash") != expected_actor_context_hash:
            layer_blockers["completion_audit"].append(
                "completion audit ActorContext contract binding mismatch"
            )
        if completion_layer.get("documentation_contract_hash") != expected_documentation_hash:
            layer_blockers["completion_audit"].append(
                "completion audit documentation contract binding mismatch"
            )
        artifact_bindings = {
            "live_postgresql_artifact_hash": "live_postgresql",
            "operator_cli_postgresql_artifact_hash": "operator_cli_postgresql",
            "production_container_lifecycle_artifact_hash": ("production_container_lifecycle"),
            "mcp_inspector_artifact_hash": "mcp_inspector",
            "live_chatgpt_google_artifact_hash": "live_chatgpt_google",
            "reviewer_gate_artifact_hash": "reviewer_gate",
        }
        for field, layer_name in artifact_bindings.items():
            referenced_layer = layers_dict.get(layer_name)
            expected_hash = (
                referenced_layer.get("evidence_artifact_hash")
                if isinstance(referenced_layer, Mapping)
                else None
            )
            if completion_layer.get(field) != expected_hash:
                layer_blockers["completion_audit"].append(
                    f"completion audit artifact binding mismatch: {field}"
                )

    if packet_blockers:
        layer_statuses = {name: "failed" for name in layer_names}
    else:
        layer_statuses = {
            name: "passed" if not layer_blockers[name] else "failed" for name in layer_names
        }
    blockers = [*packet_blockers]
    for layer_name in layer_names:
        blockers.extend(layer_blockers[layer_name])
    passed = not blockers and all(status == "passed" for status in layer_statuses.values())
    return {
        "passed": passed,
        "blockers": blockers,
        "blocker_count": len(blockers),
        "packet_hash": packet_hash,
        "layer_statuses": layer_statuses,
        "layer_artifact_hashes": layer_artifact_hashes,
    }


def validate_report(
    report: Any,
    *,
    external_evidence: Any = None,
    operator_execution_authority_pin: Mapping[str, Any] | None = None,
    production_container_lifecycle_evidence: Any = None,
    _local_completion_context: _LocalCompletionContext | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(report, dict):
        return {"passed": False, "status": "failed", "blocker_count": 1}
    try:
        trusted_local_context = _local_completion_context or _run_local_completion_context()
        if not isinstance(trusted_local_context, _LocalCompletionContext):
            raise TypeError("trusted local completion context is invalid")
    except Exception:
        trusted_local_context = None
        blockers.append("trusted local completion execution failed")
    expected = {
        "report_type",
        "status",
        "implementation_base_hash",
        "metrics",
        "safe_outputs",
        "evidence_layers",
        "claim_boundary",
    }
    if "validation" in report:
        expected.add("validation")
    _exact_keys(report, expected, "report", blockers)
    if report.get("report_type") != "issue20_oauth_mcp_harness":
        blockers.append("report_type mismatch")
    if report.get("status") not in {"passed", "failed"}:
        blockers.append("status mismatch")
    if not _is_sha256(report.get("implementation_base_hash")):
        blockers.append("implementation base hash is invalid")
    metrics = _mapping(report.get("metrics"), "metrics", blockers)
    _exact_keys(metrics, set(REQUIRED_METRICS), "metrics", blockers)
    for key in REQUIRED_METRICS:
        if not isinstance(metrics.get(key), bool):
            blockers.append(f"metric must be boolean: {key}")
    all_primary = all(metrics.get(key) is True for key in REQUIRED_METRICS[:-1])
    if metrics.get("deterministic_fake_e2e_passed") is not all_primary:
        blockers.append("deterministic fake E2E aggregate is inconsistent")
    expected_status = "passed" if metrics.get("deterministic_fake_e2e_passed") else "failed"
    if report.get("status") != expected_status:
        blockers.append("report status is inconsistent with primary metrics")
    safe_outputs = _mapping(report.get("safe_outputs"), "safe_outputs", blockers)
    _exact_keys(
        safe_outputs,
        {
            "implementation_contract_hash",
            "manifest_hash",
            "changed_function_set_hash",
            "scenario_contract_hash",
            "http_exchange_shape_hash",
            "audit_lineage_shape_hash",
            "negotiated_protocol_version_hash",
            "supported_protocol_matrix_hash",
            "manifest_test_set_hash",
            "executed_test_set_hash",
            "function_coverage_pairs_hash",
            "function_entry_count",
            "onboarded_function_count",
            "pending_function_count",
            "changed_function_count",
            "test_id_count",
            "manifest_requested_test_count",
            "manifest_resolved_test_count",
            "manifest_run_count",
            "manifest_pass_count",
            "manifest_skip_count",
            "manifest_failure_count",
            "manifest_error_count",
            "manifest_expected_failure_count",
            "manifest_unexpected_success_count",
            "manifest_resolution_blocker_count",
            "manifest_covered_function_count",
            "manifest_checked_pair_count",
            "manifest_execution_blocker_count",
            "local_completion_audit_report_hash",
            "actor_context_contract_hash",
            "documentation_contract_hash",
            "issue20_completion_journey_manifest_hash",
            "external_evidence_packet_hash",
            "live_postgresql_artifact_hash",
            "operator_cli_postgresql_artifact_hash",
            "production_container_lifecycle_artifact_hash",
            "mcp_inspector_artifact_hash",
            "live_chatgpt_google_artifact_hash",
            "reviewer_gate_artifact_hash",
            "completion_audit_artifact_hash",
            "external_evidence_blocker_count",
            "http_exchange_count",
            "negative_case_count",
            "rollback_case_count",
            "audit_event_count",
        },
        "safe_outputs",
        blockers,
    )
    for key, value in safe_outputs.items():
        if key.endswith("_hash") and not _is_sha256(value):
            blockers.append(f"safe output hash is invalid: {key}")
        if key.endswith("_count") and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            blockers.append(f"safe output count is invalid: {key}")
    expected_local_completion_hash = _local_completion_audit_report_hash(
        implementation_base_hash=str(report.get("implementation_base_hash", "")),
        metrics=metrics,
        safe_outputs=safe_outputs,
    )
    if safe_outputs.get("local_completion_audit_report_hash") != expected_local_completion_hash:
        blockers.append("local completion-audit report hash mismatch")
    if trusted_local_context is not None:
        if report.get("implementation_base_hash") != trusted_local_context.implementation_base_hash:
            blockers.append("implementation base does not match trusted local execution")
        if metrics != trusted_local_context.metrics:
            blockers.append("metrics do not match trusted local execution")
        for key in _LOCAL_COMPLETION_SAFE_OUTPUT_FIELDS:
            if safe_outputs.get(key) != trusted_local_context.safe_outputs.get(key):
                blockers.append(f"safe output does not match trusted local execution: {key}")
        if (
            safe_outputs.get("local_completion_audit_report_hash")
            != trusted_local_context.local_completion_audit_report_hash
        ):
            blockers.append("local completion hash does not match trusted local execution")
    layer_names = tuple(_EXTERNAL_LAYER_FIELDS)
    if external_evidence is not None and production_container_lifecycle_evidence is not None:
        trusted_external_validation = {
            "passed": False,
            "blocker_count": 1,
            "packet_hash": _MISSING_HASH,
            "layer_statuses": {name: "failed" for name in layer_names},
            "layer_artifact_hashes": {name: _MISSING_HASH for name in layer_names},
        }
    elif production_container_lifecycle_evidence is not None:
        lifecycle_validation = validate_production_container_lifecycle_external_layer(
            production_container_lifecycle_evidence
        )
        layer_statuses = {name: "not_supplied" for name in layer_names}
        layer_statuses["production_container_lifecycle"] = lifecycle_validation["status"]
        layer_artifact_hashes = {name: _MISSING_HASH for name in layer_names}
        if lifecycle_validation["passed"]:
            layer_artifact_hashes["production_container_lifecycle"] = str(
                production_container_lifecycle_evidence["evidence_artifact_hash"]
            )
        trusted_external_validation = {
            "passed": False,
            "blocker_count": len(layer_names) - 1 + lifecycle_validation["blocker_count"],
            "packet_hash": _MISSING_HASH,
            "layer_statuses": layer_statuses,
            "layer_artifact_hashes": layer_artifact_hashes,
        }
    elif external_evidence is not None:
        trusted_external_validation = validate_external_evidence_packet(
            external_evidence,
            expected_local_harness_report_hash=(
                trusted_local_context.local_completion_audit_report_hash
                if trusted_local_context is not None
                else _MISSING_HASH
            ),
            expected_operator_execution_authority_pin=(operator_execution_authority_pin),
        )
    else:
        trusted_external_validation = {
            "passed": False,
            "blocker_count": len(layer_names),
            "packet_hash": _MISSING_HASH,
            "layer_statuses": {name: "not_supplied" for name in layer_names},
            "layer_artifact_hashes": {name: _MISSING_HASH for name in layer_names},
        }
    if safe_outputs.get("implementation_contract_hash") != issue20_implementation_contract_hash(
        ROOT
    ):
        blockers.append("current implementation contract hash mismatch")
    if safe_outputs.get("actor_context_contract_hash") != _repository_contract_hash(
        _ACTOR_CONTEXT_CONTRACT_PATHS
    ):
        blockers.append("ActorContext contract hash mismatch")
    if safe_outputs.get("documentation_contract_hash") != _repository_contract_hash(
        _DOCUMENTATION_CONTRACT_PATHS
    ):
        blockers.append("documentation contract hash mismatch")
    if safe_outputs.get("issue20_completion_journey_manifest_hash") != sha256_json(
        _ISSUE20_COMPLETION_JOURNEYS
    ):
        blockers.append("issue #20 completion journey manifest hash mismatch")
    manifest_execution_clean = (
        safe_outputs.get("manifest_requested_test_count", 0) > 0
        and safe_outputs.get("manifest_resolved_test_count")
        == safe_outputs.get("manifest_requested_test_count")
        and safe_outputs.get("manifest_run_count")
        == safe_outputs.get("manifest_requested_test_count")
        and safe_outputs.get("manifest_pass_count")
        == safe_outputs.get("manifest_requested_test_count")
        and all(
            safe_outputs.get(key) == 0
            for key in (
                "manifest_skip_count",
                "manifest_failure_count",
                "manifest_error_count",
                "manifest_expected_failure_count",
                "manifest_unexpected_success_count",
                "manifest_resolution_blocker_count",
                "manifest_execution_blocker_count",
            )
        )
    )
    if metrics.get("function_test_execution_verified") is not manifest_execution_clean:
        blockers.append("function test-execution metric is inconsistent with exact suite counts")
    manifest_complete = (
        safe_outputs.get("function_entry_count")
        == safe_outputs.get("changed_function_count")
        == safe_outputs.get("onboarded_function_count")
        and safe_outputs.get("pending_function_count") == 0
    )
    if metrics.get("function_manifest_verified") is not manifest_complete:
        blockers.append("function manifest metric is inconsistent with onboarded/pending counts")
    expected_onboarding = manifest_complete and manifest_execution_clean
    if metrics.get("function_onboarding_verified") is not expected_onboarding:
        blockers.append("function onboarding aggregate is inconsistent")
    layers = _mapping(report.get("evidence_layers"), "evidence_layers", blockers)
    _exact_keys(
        layers,
        {
            "deterministic_fake_http_e2e_status",
            "function_execution_status",
            "live_postgresql_rollback_status",
            "operator_cli_postgresql_status",
            "production_container_lifecycle_status",
            "mcp_inspector_remote_status",
            "live_https_chatgpt_google_status",
            "reviewer_gate_status",
            "completion_audit_status",
        },
        "evidence_layers",
        blockers,
    )
    if layers.get("deterministic_fake_http_e2e_status") != expected_status:
        blockers.append("deterministic evidence-layer status mismatch")
    expected_execution_status = (
        "passed" if metrics.get("function_test_execution_verified") else "failed"
    )
    if layers.get("function_execution_status") != expected_execution_status:
        blockers.append("function-execution evidence-layer status mismatch")
    for key in (
        "live_postgresql_rollback_status",
        "operator_cli_postgresql_status",
        "production_container_lifecycle_status",
        "mcp_inspector_remote_status",
        "live_https_chatgpt_google_status",
        "reviewer_gate_status",
        "completion_audit_status",
    ):
        if layers.get(key) not in {"not_supplied", "failed", "passed"}:
            blockers.append(f"unsupported evidence-layer claim: {key}")
    external_layer_keys = {
        "supports_live_postgresql_rollback_claim": "live_postgresql_rollback_status",
        "supports_operator_cli_postgresql_claim": "operator_cli_postgresql_status",
        "supports_production_container_lifecycle_claim": ("production_container_lifecycle_status"),
        "supports_mcp_inspector_remote_claim": "mcp_inspector_remote_status",
        "supports_live_https_chatgpt_google_claim": ("live_https_chatgpt_google_status"),
    }
    external_layers_passed = all(
        layers.get(key) == "passed"
        for key in (
            "live_postgresql_rollback_status",
            "operator_cli_postgresql_status",
            "production_container_lifecycle_status",
            "mcp_inspector_remote_status",
            "live_https_chatgpt_google_status",
            "reviewer_gate_status",
            "completion_audit_status",
        )
    )
    external_blocker_count = safe_outputs.get("external_evidence_blocker_count")
    if (
        safe_outputs.get("external_evidence_packet_hash")
        != trusted_external_validation["packet_hash"]
    ):
        blockers.append("external evidence packet hash does not match trusted input")
    if external_blocker_count != trusted_external_validation["blocker_count"]:
        blockers.append("external evidence blocker count does not match trusted input")
    for layer_name, status_key in _EXTERNAL_REPORT_STATUS_FIELDS.items():
        if layers.get(status_key) != trusted_external_validation["layer_statuses"][layer_name]:
            blockers.append(f"external evidence status does not match trusted input: {layer_name}")
    for layer_name, artifact_key in _EXTERNAL_REPORT_ARTIFACT_FIELDS.items():
        if (
            safe_outputs.get(artifact_key)
            != trusted_external_validation["layer_artifact_hashes"][layer_name]
        ):
            blockers.append(
                f"external evidence artifact does not match trusted input: {layer_name}"
            )
    if external_layers_passed and external_blocker_count != 0:
        blockers.append("passed external evidence layers must have zero blockers")
    if not external_layers_passed and external_blocker_count == 0:
        blockers.append("incomplete external evidence layers must retain a blocker")
    claims = _mapping(report.get("claim_boundary"), "claim_boundary", blockers)
    _exact_keys(
        claims,
        {
            "supports_deterministic_fake_oauth_mcp_e2e_claim",
            "supports_live_postgresql_rollback_claim",
            "supports_operator_cli_postgresql_claim",
            "supports_production_container_lifecycle_claim",
            "supports_mcp_inspector_remote_claim",
            "supports_live_https_chatgpt_google_claim",
            "supports_external_evidence_packet_contract_claim",
            "supports_issue20_closure_claim",
            "requires_independent_issue20_completion_audit",
            "supports_production_ready_claim",
        },
        "claim_boundary",
        blockers,
    )
    if claims.get("supports_deterministic_fake_oauth_mcp_e2e_claim") is not metrics.get(
        "deterministic_fake_e2e_passed"
    ):
        blockers.append("deterministic claim mismatch")
    for claim_key, layer_key in external_layer_keys.items():
        if claims.get(claim_key) is not (layers.get(layer_key) == "passed"):
            blockers.append(f"external evidence claim mismatch: {claim_key}")
    expected_packet_contract_claim = trusted_external_validation["passed"]
    if (
        claims.get("supports_external_evidence_packet_contract_claim")
        is not expected_packet_contract_claim
    ):
        blockers.append("external evidence packet contract claim mismatch")
    if claims.get("supports_issue20_closure_claim") is not False:
        blockers.append("issue #20 closure remains an independent completion-audit decision")
    if claims.get("requires_independent_issue20_completion_audit") is not True:
        blockers.append("independent issue #20 completion audit must remain required")
    if claims.get("supports_production_ready_claim") is not False:
        blockers.append("production-ready claim must remain false")
    if "validation" in report:
        embedded = report.get("validation")
        if not isinstance(embedded, dict):
            blockers.append("embedded validation must be an object")
        else:
            _exact_keys(embedded, {"passed", "status", "blocker_count"}, "validation", blockers)
            expected_embedded_passed = not blockers
            expected_embedded_status = "passed" if expected_embedded_passed else "failed"
            expected_embedded_blocker_count = len(blockers)
            if embedded.get("passed") is not expected_embedded_passed:
                blockers.append("embedded validation passed flag mismatch")
            if embedded.get("status") != expected_embedded_status:
                blockers.append("embedded validation status mismatch")
            if embedded.get("blocker_count") != expected_embedded_blocker_count:
                blockers.append("embedded validation blocker count mismatch")
    try:
        assert_safe_harness_report(
            {key: value for key, value in report.items() if key != "validation"}
        )
    except AssertionError:
        blockers.append("report contains sensitive OAuth, private, path, or SQL material")
    return {
        "passed": not blockers,
        "status": "passed" if not blockers else "failed",
        "blocker_count": len(blockers),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--validate-report", type=Path)
    parser.add_argument(
        "--issue20-finalization-action",
        choices=(
            "build-preclosure-manifest",
            "validate-preclosure-manifest",
            "build-completion-transition",
            "validate-completion-transition",
        ),
    )
    parser.add_argument("--preclosure-manifest", type=Path)
    parser.add_argument("--completion-transition", type=Path)
    parser.add_argument("--expected-local-harness-report-hash")
    parser.add_argument("--operator-attest-finalization", action="store_true")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--external-evidence", type=Path)
    input_group.add_argument("--operator-cli-postgresql-report", type=Path)
    input_group.add_argument("--production-container-lifecycle-evidence", type=Path)
    input_group.add_argument("--aggregate-lifecycle-reports", nargs="+", type=Path)
    parser.add_argument("--operator-cli-postgresql-authority", type=Path)
    parser.add_argument("--operator-cli-postgresql-authority-pin", type=Path)
    parser.add_argument("--operator-attest-postgresql", action="store_true")
    parser.add_argument("--operator-attest-lifecycle", action="store_true")
    args = parser.parse_args(argv)
    if args.issue20_finalization_action is not None:
        if (
            args.external_evidence is None
            or args.operator_cli_postgresql_authority_pin is None
            or not _is_sha256(args.expected_local_harness_report_hash)
            or args.expected_local_harness_report_hash == _MISSING_HASH
        ):
            parser.error(
                "Issue #20 finalization requires --external-evidence, "
                "--operator-cli-postgresql-authority-pin, and a real "
                "--expected-local-harness-report-hash"
            )
        action = args.issue20_finalization_action
        if (
            action
            in {
                "build-completion-transition",
                "validate-completion-transition",
            }
            and args.preclosure_manifest is None
        ):
            parser.error(f"{action} requires --preclosure-manifest")
        if action == "validate-completion-transition" and args.completion_transition is None:
            parser.error("validate-completion-transition requires --completion-transition")
        if action == "validate-preclosure-manifest" and args.preclosure_manifest is None:
            parser.error("validate-preclosure-manifest requires --preclosure-manifest")
        if action.startswith("build-") and not args.operator_attest_finalization:
            parser.error(f"{action} requires --operator-attest-finalization")
        try:
            external_evidence = json.loads(args.external_evidence.read_text(encoding="utf-8"))
            operator_execution_authority_pin = json.loads(
                args.operator_cli_postgresql_authority_pin.read_text(encoding="utf-8")
            )
            preclosure_manifest = (
                json.loads(args.preclosure_manifest.read_text(encoding="utf-8"))
                if args.preclosure_manifest is not None
                else None
            )
            completion_transition = (
                json.loads(args.completion_transition.read_text(encoding="utf-8"))
                if args.completion_transition is not None
                else None
            )
        except (OSError, json.JSONDecodeError, UnicodeError):
            artifact: dict[str, Any] = {
                "artifact_type": "issue20_finalization_cli_validation_v1",
                "status": "failed",
                "passed": False,
                "blocker_count": 1,
            }
        else:
            if action == "build-preclosure-manifest":
                artifact = build_issue20_preclosure_manifest(
                    external_evidence,
                    expected_local_harness_report_hash=(args.expected_local_harness_report_hash),
                    expected_operator_execution_authority_pin=(operator_execution_authority_pin),
                    operator_attested=True,
                    root=ROOT,
                )
            elif action == "validate-preclosure-manifest":
                artifact = validate_issue20_preclosure_manifest(
                    preclosure_manifest,
                    external_evidence=external_evidence,
                    expected_local_harness_report_hash=(args.expected_local_harness_report_hash),
                    expected_operator_execution_authority_pin=(operator_execution_authority_pin),
                    root=ROOT,
                )
            elif action == "build-completion-transition":
                artifact = build_issue20_completion_transition(
                    external_evidence,
                    preclosure_manifest=preclosure_manifest,
                    expected_local_harness_report_hash=(args.expected_local_harness_report_hash),
                    expected_operator_execution_authority_pin=(operator_execution_authority_pin),
                    operator_attested=True,
                    root=ROOT,
                )
            else:
                artifact = validate_issue20_completion_transition(
                    completion_transition,
                    external_evidence=external_evidence,
                    preclosure_manifest=preclosure_manifest,
                    expected_local_harness_report_hash=(args.expected_local_harness_report_hash),
                    expected_operator_execution_authority_pin=(operator_execution_authority_pin),
                    root=ROOT,
                )
        if action.startswith("build-") and (not artifact or artifact.get("status") != "passed"):
            print(
                json.dumps(artifact or _FINALIZATION_BUILD_REJECTED, sort_keys=True),
                file=sys.stderr,
            )
            return 1
        try:
            write_json_atomic(args.output, artifact)
        except (OSError, UnicodeError):
            try:
                args.output.with_suffix(f"{args.output.suffix}.tmp").unlink(missing_ok=True)
            except OSError:
                pass
            print(json.dumps(_OUTPUT_WRITE_ERROR, sort_keys=True), file=sys.stderr)
            return 1
        if action.startswith("build-"):
            return 0 if artifact else 1
        return 0 if artifact.get("passed") is True else 1
    if args.validate_report is not None and any(
        (
            args.operator_cli_postgresql_report is not None,
            args.aggregate_lifecycle_reports is not None,
            args.operator_attest_postgresql,
            args.operator_attest_lifecycle,
        )
    ):
        parser.error(
            "--validate-report may only be combined with --external-evidence or "
            "--production-container-lifecycle-evidence"
        )
    if args.operator_cli_postgresql_report is not None:
        try:
            operator_report = json.loads(
                args.operator_cli_postgresql_report.read_text(encoding="utf-8")
            )
            operator_execution_authority = None
            operator_execution_authority_pin = None
            if args.operator_cli_postgresql_authority is not None:
                operator_execution_authority = json.loads(
                    args.operator_cli_postgresql_authority.read_text(encoding="utf-8")
                )
            if args.operator_cli_postgresql_authority_pin is not None:
                operator_execution_authority_pin = json.loads(
                    args.operator_cli_postgresql_authority_pin.read_text(encoding="utf-8")
                )
            layer = build_operator_cli_postgresql_external_layer(
                operator_report,
                operator_attested=args.operator_attest_postgresql,
                trusted_execution_authority=operator_execution_authority,
                trusted_execution_authority_pin=operator_execution_authority_pin,
            )
        except (OSError, json.JSONDecodeError, UnicodeError):
            layer = {
                "artifact_type": _OPERATOR_EXTERNAL_LAYER_BINDING_TYPE,
                "status": "failed",
                "error_code": "operator_evidence_input_invalid",
            }
        except OperatorEvidenceError as error:
            layer = {
                "artifact_type": _OPERATOR_EXTERNAL_LAYER_BINDING_TYPE,
                "status": "failed",
                "error_code": error.code,
            }
        try:
            write_json_atomic(args.output, layer)
        except (OSError, UnicodeError):
            try:
                args.output.with_suffix(f"{args.output.suffix}.tmp").unlink(missing_ok=True)
            except OSError:
                pass
            print(json.dumps(_OUTPUT_WRITE_ERROR, sort_keys=True), file=sys.stderr)
            return 1
        return 0 if layer.get("status") == "passed" else 1
    if args.aggregate_lifecycle_reports is not None:
        try:
            reports = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in args.aggregate_lifecycle_reports
            ]
            layer = aggregate_production_container_lifecycle_reports(
                reports,
                operator_attested=args.operator_attest_lifecycle,
            )
        except (OSError, json.JSONDecodeError, UnicodeError):
            layer = {
                "artifact_type": _LIFECYCLE_EXTERNAL_LAYER_BINDING_TYPE,
                "status": "failed",
                "error_code": "lifecycle_report_input_invalid",
            }
        except LifecycleEvidenceError as error:
            layer = {
                "artifact_type": _LIFECYCLE_EXTERNAL_LAYER_BINDING_TYPE,
                "status": "failed",
                "error_code": error.code,
            }
        try:
            write_json_atomic(args.output, layer)
        except (OSError, UnicodeError):
            try:
                args.output.with_suffix(f"{args.output.suffix}.tmp").unlink(missing_ok=True)
            except OSError:
                pass
            print(json.dumps(_OUTPUT_WRITE_ERROR, sort_keys=True), file=sys.stderr)
            return 1
        return 0 if layer.get("status") == "passed" else 1
    if args.operator_attest_postgresql:
        parser.error("--operator-attest-postgresql requires --operator-cli-postgresql-report")
    if args.operator_attest_lifecycle:
        parser.error("--operator-attest-lifecycle requires --aggregate-lifecycle-reports")
    external_evidence: Any = None
    external_evidence_requested = args.external_evidence is not None
    if args.external_evidence is not None:
        try:
            external_evidence = json.loads(args.external_evidence.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            # The public report records only a failed packet hash/status contract;
            # the operator path and parse detail never enter report output.
            external_evidence = {"external_evidence_input_invalid": True}
    operator_execution_authority_pin: Any = None
    if args.operator_cli_postgresql_authority_pin is not None:
        try:
            operator_execution_authority_pin = json.loads(
                args.operator_cli_postgresql_authority_pin.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, UnicodeError):
            operator_execution_authority_pin = None
    lifecycle_evidence: Any = None
    lifecycle_evidence_requested = args.production_container_lifecycle_evidence is not None
    if args.production_container_lifecycle_evidence is not None:
        try:
            lifecycle_evidence = json.loads(
                args.production_container_lifecycle_evidence.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError, UnicodeError):
            lifecycle_evidence = {"lifecycle_evidence_input_invalid": True}
    if args.validate_report is not None:
        report = json.loads(args.validate_report.read_text(encoding="utf-8"))
        validation = validate_report(
            report,
            external_evidence=external_evidence,
            operator_execution_authority_pin=operator_execution_authority_pin,
            production_container_lifecycle_evidence=lifecycle_evidence,
        )
        try:
            write_json_atomic(args.output, validation)
        except (OSError, UnicodeError):
            try:
                args.output.with_suffix(f"{args.output.suffix}.tmp").unlink(missing_ok=True)
            except OSError:
                pass
            print(json.dumps(_OUTPUT_WRITE_ERROR, sort_keys=True), file=sys.stderr)
            return 1
        return 0 if validation["passed"] else 1
    if lifecycle_evidence_requested:
        report = run_oauth_mcp_harness(
            production_container_lifecycle_evidence=lifecycle_evidence,
        )
    else:
        report = run_oauth_mcp_harness(
            external_evidence=external_evidence,
            operator_execution_authority_pin=operator_execution_authority_pin,
        )
    try:
        write_json_atomic(args.output, report)
    except (OSError, UnicodeError):
        try:
            args.output.with_suffix(f"{args.output.suffix}.tmp").unlink(missing_ok=True)
        except OSError:
            pass
        print(json.dumps(_OUTPUT_WRITE_ERROR, sort_keys=True), file=sys.stderr)
        return 1
    if lifecycle_evidence_requested:
        return (
            0
            if report["validation"]["passed"]
            and report["status"] == "passed"
            and report["claim_boundary"]["supports_production_container_lifecycle_claim"]
            and not report["claim_boundary"]["supports_external_evidence_packet_contract_claim"]
            and not report["claim_boundary"]["supports_issue20_closure_claim"]
            and not report["claim_boundary"]["supports_production_ready_claim"]
            else 1
        )
    external_contract_passed = report["claim_boundary"][
        "supports_external_evidence_packet_contract_claim"
    ]
    return (
        0
        if report["validation"]["passed"]
        and report["status"] == "passed"
        and (not external_evidence_requested or external_contract_passed)
        else 1
    )


def _safe_hash(value: Any) -> str:
    return value if _is_sha256(value) else sha256_json({"missing": True})


def _safe_count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _hash_external_packet(packet: Any) -> str:
    try:
        return sha256_json(packet)
    except (TypeError, ValueError):
        return _MISSING_HASH


def _validate_external_hash_fields(
    layer_name: str,
    layer: Mapping[str, Any],
    blockers: list[str],
) -> None:
    hash_fields = sorted(
        field for field in _EXTERNAL_LAYER_FIELDS[layer_name] if field.endswith("_hash")
    )
    hash_values: list[str] = []
    for field in hash_fields:
        value = layer.get(field)
        if not _is_sha256(value) or value == _MISSING_HASH:
            blockers.append(f"external evidence hash is invalid: {layer_name}.{field}")
            continue
        hash_values.append(str(value))
    if len(hash_values) != len(set(hash_values)):
        blockers.append(f"external evidence hashes must be independently bound: {layer_name}")
    expected_sequence_hash = {
        "production_container_lifecycle": sha256_json(_PRODUCTION_CONTAINER_LIFECYCLE_SEQUENCE),
        "mcp_inspector": sha256_json(_MCP_INSPECTOR_SEQUENCE),
        "live_chatgpt_google": sha256_json(_LIVE_CHATGPT_GOOGLE_SEQUENCE),
    }.get(layer_name)
    if expected_sequence_hash is not None and layer.get("sequence_hash") != expected_sequence_hash:
        blockers.append(f"external evidence sequence contract mismatch: {layer_name}")
    if layer_name == "completion_audit" and layer.get("journey_manifest_hash") != sha256_json(
        _ISSUE20_COMPLETION_JOURNEYS
    ):
        blockers.append("completion audit journey manifest mismatch")
    if layer_name == "live_chatgpt_google" and layer.get(
        "audit_lineage_manifest_hash"
    ) != sha256_json(_LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE):
        blockers.append("live ChatGPT/Google audit lineage manifest mismatch")
    if layer_name == "live_chatgpt_google" and layer.get(
        "audit_lineage_field_set_hash"
    ) != sha256_json(_LIVE_CHATGPT_GOOGLE_AUDIT_LINEAGE_FIELDS):
        blockers.append("live ChatGPT/Google audit lineage field-set mismatch")


def _validate_external_attestations(
    layer_name: str,
    value: Any,
    blockers: list[str],
) -> None:
    if not isinstance(value, Mapping):
        blockers.append(f"external evidence attestations must be an object: {layer_name}")
        return
    attestations = dict(value)
    required = set(_EXTERNAL_ATTESTATIONS[layer_name])
    _exact_keys(
        attestations,
        required,
        f"external_evidence.layers.{layer_name}.attestations",
        blockers,
    )
    for key in required:
        if attestations.get(key) is not True:
            blockers.append(f"external evidence attestation must be true: {layer_name}.{key}")


def _validate_external_layer_counts(
    layer_name: str,
    layer: Mapping[str, Any],
    blockers: list[str],
) -> None:
    counts: dict[str, int] = {}
    for field in sorted(
        field for field in _EXTERNAL_LAYER_FIELDS[layer_name] if field.endswith("_count")
    ):
        value = layer.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            blockers.append(f"external evidence count is invalid: {layer_name}.{field}")
            continue
        counts[field] = value

    if layer_name == "live_postgresql":
        if layer.get("endpoint_scheme") != "postgresql":
            blockers.append("live PostgreSQL evidence must identify only the postgresql scheme")
        if counts.get("run_count", 0) < 1:
            blockers.append("live PostgreSQL evidence must include at least one executed run")
        if counts.get("pass_count") != counts.get("run_count"):
            blockers.append("live PostgreSQL evidence run and pass counts must match")
        if counts.get("failure_count") != 0 or counts.get("skip_count") != 0:
            blockers.append("live PostgreSQL evidence cannot contain failures or skips")
        if counts.get("transaction_rollback_probe_count", 0) < 1:
            blockers.append("live PostgreSQL evidence must include a rollback probe")
        if counts.get("production_smoke_probe_count", 0) < 1:
            blockers.append("live PostgreSQL evidence must include a production smoke probe")
        exact_journey_counts = {
            "fresh_database_count": 1,
            "migration_count": 1,
            "first_owner_bootstrap_count": 1,
            "persisted_auth_count": 1,
            "persisted_upload_count": 1,
            "restart_recovery_count": 1,
            "second_user_invitation_count": 1,
            "revocation_count": 1,
            "post_relink_old_token_denial_count": 1,
            "revoked_token_sessions_after_relink_count": 1,
            "relink_distinct_token_session_count": 1,
            "expiry_denial_count": 1,
            "relink_count": 1,
            "signing_key_rotation_count": 1,
            "overlap_old_token_verification_count": 1,
            "overlap_jwks_public_key_count": 2,
            "new_key_token_verification_count": 1,
            "post_overlap_old_token_denial_count": 1,
            "post_overlap_jwks_public_key_count": 1,
            "post_overlap_new_token_verification_count": 1,
            "private_signing_key_exposure_count": 0,
        }
        for field, expected in exact_journey_counts.items():
            if counts.get(field) != expected:
                blockers.append(f"live PostgreSQL evidence requires {field}={expected}")
        if counts.get("persisted_audit_count", 0) < 1:
            blockers.append("live PostgreSQL evidence must include persisted audit rows")
        return

    if layer_name == "operator_cli_postgresql":
        if layer.get("endpoint_scheme") != "container_postgresql":
            blockers.append("operator CLI PostgreSQL evidence must use container scope")
        exact_counts = {
            "run_count": 1,
            "pass_count": 1,
            "failure_count": 0,
            "skip_count": 0,
            "runtime_image_build_count": 1,
            "fresh_database_count": 1,
            "generated_secret_count": 6,
            "idempotent_secret_rerun_count": 1,
            "migration_success_count": 1,
            **{
                layer_field: _OPERATOR_V2_SOURCE_EXACT_COUNTS[source_field]
                for layer_field, source_field in _OPERATOR_LAYER_COUNT_SOURCES.items()
            },
        }
        for field, expected in exact_counts.items():
            if counts.get(field) != expected:
                blockers.append(f"operator CLI PostgreSQL evidence requires {field}={expected}")
        return

    if layer_name == "production_container_lifecycle":
        if layer.get("endpoint_scheme") != "container":
            blockers.append("production container lifecycle evidence must use container scope")
        run_count = counts.get("run_count", 0)
        if run_count < 2:
            blockers.append("production container lifecycle requires two fresh runs")
        if counts.get("pass_count") != run_count:
            blockers.append("production container lifecycle run and pass counts must match")
        if counts.get("failure_count") != 0 or counts.get("skip_count") != 0:
            blockers.append("production container lifecycle cannot contain failures or skips")
        per_run_counts = {
            "compose_healthcheck_success_count": 3,
            "compose_migration_success_count": 1,
            "compose_old_snapshot_retirement_count": 2,
            "compose_postgres_0400_secret_read_count": 1,
            "compose_preflight_success_count": 1,
            "compose_runtime_ready_count": 3,
            "compose_secret_snapshot_count": 3,
            "operator_owned_0400_secret_count": 7,
            "runtime_process_start_count": 4,
            "runtime_ready_count": 4,
            "sigterm_clean_exit_count": 4,
            "database_release_count": 4,
            "stateful_restart_count": 1,
            "bearer_whoami_success_count": 2,
            "upload_session_count": 1,
            "forgery_denial_count": 1,
            "persisted_user_count": 1,
            "persisted_external_identity_count": 1,
            "persisted_token_session_count": 1,
            "persisted_file_audit_count": 1,
            "postgres_mcp_allowed_audit_count": 3,
            "postgres_mcp_denied_audit_count": 1,
            "persisted_state_snapshot_count": 2,
            "jwks_initial_public_key_count": 1,
            "jwks_overlap_public_key_count": 2,
            "jwks_retired_public_key_count": 1,
        }
        for field, per_run in per_run_counts.items():
            expected = run_count * per_run
            if counts.get(field) != expected:
                blockers.append(f"production container lifecycle requires {field}={expected}")
        if counts.get("compose_service_count", 0) < run_count * 5:
            blockers.append(
                "production container lifecycle requires at least five Compose services per run"
            )
        return

    if layer_name == "mcp_inspector":
        if layer.get("endpoint_scheme") != "https":
            blockers.append("MCP Inspector evidence must use a remote HTTPS endpoint")
        for field, expected in _MCP_INSPECTOR_EXACT_COUNTS.items():
            if counts.get(field) != expected:
                blockers.append(f"MCP Inspector evidence requires {field}={expected}")
        return

    if layer_name == "live_chatgpt_google":
        if layer.get("endpoint_scheme") != "https":
            blockers.append("live ChatGPT and Google evidence must use public HTTPS")
        for field, expected in _LIVE_CHATGPT_GOOGLE_EXACT_COUNTS.items():
            if counts.get(field) != expected:
                blockers.append(f"live ChatGPT and Google evidence requires {field}={expected}")
        return

    if layer_name == "reviewer_gate":
        if counts.get("reviewer_count") != 3:
            blockers.append("reviewer evidence must contain the configured three reviewers")
        if counts.get("agreement_count") != counts.get("reviewer_count"):
            blockers.append("every configured reviewer must explicitly agree")
        if counts.get("blocking_finding_count") != 0:
            blockers.append("reviewer evidence cannot retain a blocking finding")
        return

    if layer_name == "completion_audit":
        journey_count = len(_ISSUE20_COMPLETION_JOURNEYS)
        if counts.get("journey_count") != journey_count:
            blockers.append(f"completion audit requires journey_count={journey_count}")
        if counts.get("passed_journey_count") != journey_count:
            blockers.append(f"completion audit requires passed_journey_count={journey_count}")
        if counts.get("missing_journey_count") != 0:
            blockers.append("completion audit cannot omit a required journey")
        if counts.get("blocking_finding_count") != 0:
            blockers.append("completion audit cannot retain a blocking finding")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _mapping(value: Any, context: str, blockers: list[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        blockers.append(f"{context} must be an object")
        return {}
    return dict(value)


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    context: str,
    blockers: list[str],
) -> None:
    if set(value) != expected:
        blockers.append(f"{context} keys mismatch")


if __name__ == "__main__":
    raise SystemExit(main())
